import os
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit, create_sql_agent
from langchain_groq import ChatGroq
import warnings

warnings.filterwarnings("ignore")

# 1. Load Environment Variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

print("📊 Booting up SQL Agent (Structured Data Cruncher)...")

# 2. Connect to the Database
# We explicitly hide the "documents" and vector tables from the SQL agent!
db = SQLDatabase.from_uri(
    DATABASE_URL,
    ignore_tables=["documents", "langchain_pg_collection", "langchain_pg_embedding"] 
)

# 3. Initialize the LLM
llm = ChatGroq(temperature=0, model_name="meta-llama/llama-4-scout-17b-16e-instruct", api_key=GROQ_API_KEY)

# 4. Create the SQL Toolkit
toolkit = SQLDatabaseToolkit(db=db, llm=llm)

# 5. Define the Agent's Persona and Rules
custom_prefix = """You are an expert Data Analyst and Customs Agent for AutoTrade-Comply.
You have access to a PostgreSQL database containing a wide variety of structured tables covering international trade regulations, tariffs, CBAM compliance, product nomenclature, and user data.

RULES:
1. EXPLORE ALL TABLES: Always use the sql_db_list_tables and sql_db_schema tools to find the correct tables to answer the user's question. 
2. BE COMPREHENSIVE: Do not restrict yourself to just one table. If a question involves multiple domains, JOIN or query all relevant tables (like eu_nomenclature, morocco_tariffs, reach_svhc_list, client_products, etc.).
3. VERIFY: Always double-check your SQL queries for syntax errors before executing them.
4. GROUNDED ANSWERS: Answer the user's question accurately based ON THE DATABASE RESULTS ONLY.
5. NO GUESSING: If you search the tables and cannot find the specific data, DO NOT guess. Say "I don't have this data in my structured tables."
"""

# 6. Create the Execution Agent
sql_agent = create_sql_agent(
    llm=llm,
    toolkit=toolkit,
    verbose=True, # Set to True so you can watch it "think" and write SQL in your terminal!
    agent_type="zero-shot-react-description",
    prefix=custom_prefix
)

def run_sql_agent(question: str):
    """Takes a natural language question, writes SQL, runs it, and returns the answer."""
    try:
        response = sql_agent.invoke({"input": question})
        return response["output"]
    except Exception as e:
        return f"Error executing SQL search: {str(e)}"