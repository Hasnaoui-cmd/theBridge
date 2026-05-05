import os
import json
import asyncio
import operator
from typing import Annotated, TypedDict
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
import warnings

warnings.filterwarnings("ignore")

# --- Import your "Employee" Agents ---
from rag_agent import run_rag_agent
from sql_agent import run_sql_agent

# 1. Load Environment Variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
print("🕸️ Booting up LangGraph Orchestrator (Streaming Mode)...")

# 2. Define the Graph State
class GraphState(TypedDict):
    messages: Annotated[list, add_messages]
    sources: Annotated[list, operator.add]
    used_agents: Annotated[list, operator.add]

# 3. Initialize the Master LLM
llm = ChatGroq(temperature=0, model_name="meta-llama/llama-4-scout-17b-16e-instruct", api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────────────────────────
# 4. The Streaming Orchestrator
#
#    CONTEXT ANCHORING FIX:
#    Previously, chat history was passed as a single concatenated string
#    stuffed into the SystemMessage. The LLM couldn't distinguish old
#    turns from the new question and would re-answer old prompts.
#
#    Now we accept `past_messages` as a list of dicts and convert them
#    to proper LangChain HumanMessage / AIMessage objects. This gives
#    the LLM a clear conversational timeline where the LATEST
#    HumanMessage is always the user's current question.
# ─────────────────────────────────────────────────────────────────────
async def stream_orchestrator(question: str, past_messages: list):
    """
    Builds the LangGraph and yields real-time SSE tokens to the frontend.

    Args:
        question:       The user's latest question (plain string).
        past_messages:  List of dicts from Supabase, e.g.
                        [{"role": "user", "content": "..."}, {"role": "ai", "content": "..."}]
    """

    # ── Reconstruct a flat history_str for sub-agents that still need it ──
    # run_rag_agent(question, history_str) expects a plain string.
    # We build it here once and capture it in the closure.
    # Defensive: skip any malformed entries that lack 'role' or 'content'.
    try:
        history_str = "\n".join(
            [f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" 
             for msg in past_messages 
             if isinstance(msg, dict) and msg.get('content')]
        )
    except Exception:
        history_str = ""

    # --- A. DEFINE THE TOOLS ---
    @tool
    def search_structured_database(search_query: str) -> str:
        """
        CRITICAL ROUTING RULE: USE THIS TOOL ONLY IF the user provides a specific
        HS Code (e.g., '8501', '8703'), a specific product name (e.g., 'cars', 'motors'),
        or explicitly asks for numeric tariff rates, taxes, duties, or inventory data.
        DO NOT use this tool for general questions about customs procedures, definitions,
        or how things work. This tool queries a SQL database with structured numeric data.
        """
        pass

    @tool
    def search_legal_documents(search_query: str) -> str:
        """
        CRITICAL ROUTING RULE: USE THIS TOOL FOR general questions about trade laws,
        customs procedures, regulations, or definitions (e.g., 'What are the duties of...',
        'How do I clear customs', 'What is the BADR system', 'Explain the import process').
        Use this when the query is conceptual, process-oriented, or asks about how
        something works. This tool searches legal PDFs and regulatory documents.
        """
        pass

    tools = [search_structured_database, search_legal_documents]
    llm_with_tools = llm.bind_tools(tools)

    # --- B. DEFINE THE GRAPH NODES ---
    def agent_node(state: GraphState):
        """The 'Brain'."""
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def execute_tools_node(state: GraphState):
        """The 'Hands'."""
        last_message = state["messages"][-1]
        new_messages = []
        new_sources = []
        new_agents = []
        
        for tool_call in last_message.tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]
            
            if name == "search_structured_database":
                # Ensure we only get the string result from the SQL agent
                raw_result = run_sql_agent(args.get("search_query", question))
                
                # If your SQL agent returns a dict, extract just the output!
                if isinstance(raw_result, dict) and "output" in raw_result:
                    result = raw_result["output"]
                else:
                    result = str(raw_result)
                    
                new_agents.append("SQL Agent")
                new_sources.append("Enterprise SQL Database")
                
            elif name == "search_legal_documents":
                # run_rag_agent still expects (question, history_str) as strings
                result, sources = run_rag_agent(args.get("search_query", question), history_str)
                new_agents.append("RAG Agent")
                new_sources.extend(sources)
            else:
                result = "Error: Unknown tool requested."
                
            new_messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"], name=name))
            
        return {"messages": new_messages, "sources": new_sources, "used_agents": new_agents}

    def should_continue_edge(state: GraphState):
        """The 'Traffic Light'."""
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "execute_tools" 
        return END 

    # --- C. BUILD AND COMPILE THE GRAPH ---
    workflow = StateGraph(GraphState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("execute_tools", execute_tools_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue_edge, ["execute_tools", END])
    workflow.add_edge("execute_tools", "agent") 
    app = workflow.compile()

    # ─────────────────────────────────────────────────────────────────
    # D. BUILD THE NATIVE LANGCHAIN MESSAGE ARRAY
    #
    #    This is the CONTEXT ANCHORING fix. Instead of dumping history
    #    into a string, we construct a proper message timeline:
    #
    #      1. SystemMessage  — core persona instructions ONLY
    #      2. HumanMessage / AIMessage — from past_messages (history)
    #      3. HumanMessage  — the user's LATEST question (always last)
    #
    #    The LLM sees a clear turn-by-turn conversation and will
    #    always answer the FINAL HumanMessage.
    # ─────────────────────────────────────────────────────────────────
    system_msg = SystemMessage(content=(
        "You are the Master Orchestrator for an Enterprise Trade Compliance AI. "
        "Your MOST IMPORTANT job is to route the user's question to the correct tool.\n\n"
        "ROUTING RULES (follow strictly):\n"
        "1. Use 'search_structured_database' ONLY when the user asks about a SPECIFIC "
        "HS Code, product name, numeric tariff rate, tax percentage, duty amount, or inventory data. "
        "Examples: 'What is the tariff for HS 8703?', 'Show me rates for cars', 'List products in my inventory'.\n"
        "2. Use 'search_legal_documents' for ALL general, conceptual, or procedural questions "
        "about trade, customs, regulations, laws, or definitions. "
        "Examples: 'What is the BADR system?', 'How do I clear customs?', 'What are the duties of a customs broker?', "
        "'Explain the import procedure in Morocco'.\n"
        "3. If unsure, DEFAULT to 'search_legal_documents'. Never guess with the SQL database.\n\n"
        "Once you have the tool results, synthesize them into a single, cohesive, professional answer. "
        "Always answer the user's LATEST message. Do NOT re-answer previous questions."
    ))

    # Convert Supabase history dicts → LangChain message objects
    # Defensive: skip entries that are not dicts or lack content
    history_messages = []
    for msg in past_messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content:  # Skip empty messages
            continue
        if role == "user":
            history_messages.append(HumanMessage(content=str(content)))
        elif role == "ai":
            history_messages.append(AIMessage(content=str(content)))
        # Skip any other roles (system, etc.)

    # ── De-duplicate: if the latest history message is already the user's
    #    current question (because save_message ran before get_session_history),
    #    don't append it twice. Otherwise, add it as the final HumanMessage. ──
    if history_messages and isinstance(history_messages[-1], HumanMessage) and history_messages[-1].content == question:
        # The question is already the last message in history — no need to duplicate
        constructed_messages = [system_msg] + history_messages
    else:
        # Append the new question as the absolute final HumanMessage
        constructed_messages = [system_msg] + history_messages + [HumanMessage(content=question)]

    initial_state = {
        "messages": constructed_messages,
        "sources": [],
        "used_agents": []
    }

    # --- E. EXECUTE AS A REAL-TIME STREAM ---
    try:
        # astream_events lets us watch the AI as it works, step by step!
        async for event in app.astream_events(initial_state, version="v2"):
            kind = event["event"]
            
            # Catch when a tool starts running to send a UI status update
            if kind == "on_tool_start":
                tool_name = event["name"]
                if "structured_database" in tool_name:
                    yield f"data: {json.dumps({'type': 'status', 'content': '📊 Querying Enterprise Database...'})}\n\n"
                elif "legal_documents" in tool_name:
                    yield f"data: {json.dumps({'type': 'status', 'content': '📚 Scanning Legal PDFs...'})}\n\n"
                    
            # Catch the AI generating its final answer text
            elif kind == "on_chat_model_stream":
                
                # 🚀 Only stream if the speaker is the Master 'agent' node!
                # This ignores any sub-LLMs running inside your SQL or RAG tools.
                if event["metadata"].get("langgraph_node") == "agent":
                    
                    chunk = event["data"]["chunk"]
                    # Guard against BOTH tool_calls and tool_call_chunks
                    # (some LangChain versions emit tool_call_chunks during streaming)
                    has_tool_calls = getattr(chunk, "tool_calls", None)
                    has_tool_chunks = getattr(chunk, "tool_call_chunks", None)
                    
                    if not has_tool_calls and not has_tool_chunks and chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
                        # Flush the event loop so the chunk is sent immediately
                        await asyncio.sleep(0)

        # When the loop finishes, send the "done" signal
        final_meta = {
            "type": "done", 
            "sources": ["Enterprise Database", "Legal Document Vectors"], 
            "agents": "LangGraph Orchestrator"
        }
        yield f"data: {json.dumps(final_meta)}\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'type': 'token', 'content': f'Error: {str(e)}'})}\n\n"