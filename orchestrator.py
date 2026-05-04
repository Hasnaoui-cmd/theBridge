import os
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
import warnings

warnings.filterwarnings("ignore")

# --- Import your two specialized "Employee" Agents ---
from rag_agent import run_rag_agent
from sql_agent import run_sql_agent

# 1. Load Environment Variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print("👔 Booting up Orchestrator (The Master Router)...")

# 2. Initialize the fast router LLM
llm = ChatGroq(temperature=0, model_name="llama-3.1-8b-instant", api_key=GROQ_API_KEY)

# 3. The Orchestrator's Brain
router_prompt = PromptTemplate.from_template(
    """You are the Master Orchestrator for an Enterprise Trade Compliance AI. 
    Analyze the user's question and decide which specialized database it needs.
    
    RULES:
    - If the question asks for specific tax rates, tariffs, duties, HS Codes, carbon benchmarks, or client product inventory, respond with exactly: SQL
    - If the question asks about laws, registration procedures, customs rules, or general document explanations, respond with exactly: RAG
    
    User Question: {question}
    Decision (SQL or RAG):"""
)

router_chain = router_prompt | llm | StrOutputParser()

# 4. The Main Execution Function
def run_orchestrator(question: str, history_str: str):
    """Routes the question to the right agent and returns the final answer."""
    try:
        # A. Ask the LLM to classify the question
        decision = router_chain.invoke({"question": question}).strip().upper()
        
        # B. Route to the correct agent
        if "SQL" in decision:
            print(f"🚦 Orchestrator Decision: Routing to 📊 SQL Agent")
            answer = run_sql_agent(question)
            sources = ["Structured Database (Enterprise SQL Tables)"]
            agent_used = "SQL Agent"
        else:
            print(f"🚦 Orchestrator Decision: Routing to 📚 RAG Agent")
            answer, sources = run_rag_agent(question, history_str)
            agent_used = "RAG Agent"
            
        return answer, sources, agent_used
        
    except Exception as e:
        return f"Orchestrator encountered an error: {str(e)}", [], "Error"