import os
import psycopg 
from psycopg.rows import dict_row 
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
import warnings
warnings.filterwarnings("ignore")

# --- THE ONLY AI IMPORT YOU NEED ---
from orchestrator import run_orchestrator

# 1. Load Environment Variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL") 
groq_client = Groq(api_key=GROQ_API_KEY)

app = FastAPI(title="AutoTrade-Comply API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Database Helper Functions (Memory)
def save_message(session_id: str, role: str, content: str):
    """Saves a single message to Supabase."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_history (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, role, content)
            )

def get_session_history(session_id: str):
    """Retrieves the last 6 messages for a specific session."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT role, content FROM chat_history WHERE session_id = %s ORDER BY created_at DESC LIMIT 6",
                (session_id,)
            )
            records = cur.fetchall()
            records.reverse() 
            return records

# 3. Define the API Request Models
class ChatRequest(BaseModel):
    question: str
    session_id: str 

# 4. API Endpoints
@app.get("/history/{session_id}")
async def get_history_endpoint(session_id: str):
    try:
        messages = get_session_history(session_id)
        return {"messages": messages}
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        # 1. Save user message to Supabase
        save_message(request.session_id, "user", request.question)
        
        # 2. Get chat history from Supabase
        past_messages = get_session_history(request.session_id)
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in past_messages])
        
        # 3. HAND OFF TO THE ORCHESTRATOR
        answer, sources, agent_used = run_orchestrator(request.question, history_str)
        
        # 4. Save AI answer to Supabase
        save_message(request.session_id, "ai", answer)
        
        # We also send back which agent was used, so your Angular frontend can display it!
        return {"answer": answer, "sources": sources, "agent": agent_used}
        
    except Exception as e:
        return {"error": str(e)}

@app.post("/audio-chat")
async def audio_chat_endpoint(file: UploadFile = File(...), session_id: str = Form(...)):
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
                language="fr" # Setting to 'fr' helps if your users speak French!
            )
        os.remove(temp_file_path)
        user_question = transcription.text

        # 2. Save user message to Supabase (with a mic icon so you know it was voice!)
        save_message(session_id, "user", f"🎤 {user_question}")
        
        # 3. Get chat history from Supabase
        past_messages = get_session_history(session_id)
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in past_messages])
        
        # 4. HAND OFF TO THE ORCHESTRATOR
        # We pass the Whisper transcription to our new Master Router
        print(f"🎙️ Voice transcription received: {user_question}")
        answer, sources, agent_used = run_orchestrator(user_question, history_str)
        
        # 5. Save AI answer to Supabase
        save_message(session_id, "ai", answer)
        
        # Return everything to the Angular frontend
        return {
            "transcription": user_question,
            "answer": answer,
            "sources": sources,
            "agent": agent_used
        }
        
    except Exception as e:
        return {"error": str(e)}

print("✅ Server ready with Clean Architecture!")