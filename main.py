import os
import json
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from fastapi.responses import StreamingResponse
from orchestrator import stream_orchestrator
import warnings

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 1. Load Environment Variables
# ─────────────────────────────────────────────
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
groq_client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────
# 2. FastAPI App
# ─────────────────────────────────────────────
app = FastAPI(title="AutoTrade-Comply API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# 3. Database Helper Functions (Memory)
# ─────────────────────────────────────────────
def save_message(session_id: str, role: str, content: str):
    """Saves a single message to Supabase. Returns True on success, False on failure."""
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES (%s, %s, %s)",
                    (session_id, role, content)
                )
        return True
    except Exception as e:
        print(f"❌ DB SAVE ERROR for session {session_id}, role={role}: {e}")
        return False


def get_session_history(session_id: str):
    """Retrieves ALL messages for a specific session, ordered chronologically."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT role, content FROM chat_history WHERE session_id = %s ORDER BY created_at ASC",
                (session_id,)
            )
            return cur.fetchall()

# ─────────────────────────────────────────────
# 4. API Request Models
# ─────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str
    session_id: str

# ─────────────────────────────────────────────
# 5. History Endpoint
# ─────────────────────────────────────────────
@app.get("/history/{session_id}")
async def get_history_endpoint(session_id: str):
    """Returns the last 6 messages for a given session."""
    try:
        messages = get_session_history(session_id)
        return {"messages": messages}
    except Exception as e:
        print(f"❌ History retrieval error: {e}")
        return {"error": str(e)}

# ─────────────────────────────────────────────
# 6. THE TEXT CHAT ENDPOINT (Streaming + Memory)
# ─────────────────────────────────────────────
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Streams AI tokens to the frontend in real-time via SSE.
    Uses a wrapper generator to:
      1. Forward each chunk to the client instantly
      2. Accumulate token text into a full answer
      3. Save the complete answer to Supabase AFTER the stream finishes
    """
    try:
        # 1. Save user message to Supabase
        save_message(request.session_id, "user", request.question)

        # 2. Get FULL chat history from Supabase (for UI display on load)
        past_messages = get_session_history(request.session_id)

        # 3. KEEP LLM FAST & SAFE: Only feed the last 10 messages to the AI
        recent_context = past_messages[-10:] if len(past_messages) > 10 else past_messages

        # 4. THE MEMORY CATCHER WRAPPER
        async def stream_and_save():
            """Wraps the orchestrator stream: forwards chunks AND saves the final answer."""
            full_ai_answer = ""

            try:
                # 🔍 DEBUG PING: Confirm the SSE connection is alive
                print("📡 [PING] Sending connection ping to frontend...")
                yield f"data: {json.dumps({'type': 'status', 'content': 'Analyse de la requête en cours...'})}\n\n"

                # Watch the stream as it goes to the user
                # Pass sliced context — orchestrator converts to LangChain messages
                async for chunk in stream_orchestrator(request.question, recent_context):
                    print(f"📡 [STREAM] Forwarding chunk: {chunk[:80]}...")  # DEBUG

                    # Intercept token data to accumulate the full answer
                    for line in chunk.split('\n'):
                        if line.startswith("data: "):
                            try:
                                data_json = json.loads(line[6:].strip())
                                if data_json.get("type") == "token":
                                    full_ai_answer += data_json.get("content", "")
                            except json.JSONDecodeError:
                                pass  # Ignore malformed intermediate chunks

                    # Pass the chunk to the frontend INSTANTLY
                    yield chunk

            except Exception as stream_err:
                # If the stream itself errors, yield an error event to the frontend
                print(f"❌ Stream error: {stream_err}")
                yield f"data: {json.dumps({'type': 'token', 'content': f'Error during generation: {str(stream_err)}'})}\n\n"

            finally:
                # 4. Stream is finished! Save the complete answer to Supabase
                if full_ai_answer.strip():
                    success = save_message(request.session_id, "ai", full_ai_answer)
                    if success:
                        print(f"✅ AI answer saved to Supabase for session: {request.session_id} ({len(full_ai_answer)} chars)")
                    else:
                        print(f"⚠️ Failed to save AI answer for session: {request.session_id}")

        # 5. Return the streaming response with anti-buffering headers
        return StreamingResponse(
            stream_and_save(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",        # Prevent browser caching
                "Connection": "keep-alive",          # Keep the connection open
                "X-Accel-Buffering": "no"            # Disable Nginx/reverse-proxy buffering
            }
        )

    except Exception as e:
        print(f"❌ Chat endpoint error: {e}")
        return {"error": str(e)}

# ─────────────────────────────────────────────
# 7. THE AUDIO CHAT ENDPOINT (Streaming + Memory)
# ─────────────────────────────────────────────
@app.post("/audio-chat/stream")
async def audio_chat_stream_endpoint(file: UploadFile = File(...), session_id: str = Form(...)):
    """
    Accepts an audio file, transcribes it with Whisper,
    then streams the AI answer via SSE (same pattern as /chat).
    Sends a 'transcription' event first so the frontend can display what the user said.
    """
    try:
        # 1. Save and Transcribe the Audio (Whisper)
        temp_file_path = f"temp_{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            buffer.write(await file.read())

        with open(temp_file_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=(temp_file_path, audio_file.read()),
                model="whisper-large-v3",
                response_format="json",
                language="fr"  # French language support
            )
        os.remove(temp_file_path)
        user_question = transcription.text
        print(f"🎙️ Voice transcription received: {user_question}")

        # 2. Save user audio message to Supabase
        save_message(session_id, "user", f"🎤 {user_question}")

        # 3. Get FULL chat history from Supabase
        past_messages = get_session_history(session_id)

        # 4. KEEP LLM FAST & SAFE: Only feed the last 10 messages to the AI
        recent_context = past_messages[-10:] if len(past_messages) > 10 else past_messages

        # 5. THE MEMORY CATCHER WRAPPER
        async def stream_with_transcription_and_save():
            """Yields transcription first, then streams AI tokens, then saves to DB."""
            # Send the transcription event so the frontend knows what was said
            yield f"data: {json.dumps({'type': 'transcription', 'content': user_question})}\n\n"

            full_ai_answer = ""

            try:
                # 🔍 DEBUG PING: Confirm the SSE connection is alive
                print("📡 [AUDIO PING] Sending connection ping to frontend...")
                yield f"data: {json.dumps({'type': 'status', 'content': 'Analyse de la requête en cours...'})}\n\n"

                # Watch the stream as it goes to the user
                # Pass sliced context — orchestrator converts to LangChain messages
                async for chunk in stream_orchestrator(user_question, recent_context):
                    print(f"📡 [AUDIO STREAM] Forwarding chunk: {chunk[:80]}...")  # DEBUG
                    # Intercept token data to accumulate the full answer
                    for line in chunk.split('\n'):
                        if line.startswith("data: "):
                            try:
                                data_json = json.loads(line[6:].strip())
                                if data_json.get("type") == "token":
                                    full_ai_answer += data_json.get("content", "")
                            except json.JSONDecodeError:
                                pass

                    # Forward the chunk to the frontend instantly
                    yield chunk

            except Exception as stream_err:
                print(f"❌ Audio stream error: {stream_err}")
                yield f"data: {json.dumps({'type': 'token', 'content': f'Error during generation: {str(stream_err)}'})}\n\n"

            finally:
                # Stream finished — save the complete answer to Supabase
                if full_ai_answer.strip():
                    success = save_message(session_id, "ai", full_ai_answer)
                    if success:
                        print(f"✅ AI answer saved to Supabase for audio session: {session_id} ({len(full_ai_answer)} chars)")
                    else:
                        print(f"⚠️ Failed to save AI answer for audio session: {session_id}")

        # 5. Return the streaming response with anti-buffering headers
        return StreamingResponse(
            stream_with_transcription_and_save(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except Exception as e:
        print(f"❌ Audio endpoint error: {e}")
        # Return the error as a stream so the frontend SSE handler can catch it
        async def stream_error():
            yield f"data: {json.dumps({'type': 'token', 'content': f'Error: {str(e)}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'sources': [], 'agents': 'Error'})}\n\n"
        return StreamingResponse(stream_error(), media_type="text/event-stream")


print("✅ Server ready with Clean Architecture!")