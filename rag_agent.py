import os
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector  
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import warnings

warnings.filterwarnings("ignore")

# 1. Load variables explicitly in this module
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print("🧠 Booting up RAG Agent (Unstructured Document Search)...")

# 2. Setup Vector Store
embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
connection_string = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

db = PGVector(
    embeddings=embedding_model,
    collection_name="documents", 
    connection=connection_string,
    use_jsonb=True,
)
retriever = db.as_retriever(search_kwargs={"k": 6}) 

# 3. Setup LLM & Prompt
llm = ChatGroq(temperature=0, model_name="llama-3.1-8b-instant", api_key=GROQ_API_KEY)

system_prompt = (
    "You are an expert Moroccan Customs AI. "
    "answer only from the legal context provided, do not answer any other questions if the answer is not in the context say I do not know"
    "Use the context AND the Chat History to answer the question.\n\n"
    "--- CHAT HISTORY ---\n{chat_history}\n\n"
    "--- LEGAL CONTEXT ---\n{context}"
)
prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
chain = prompt | llm | StrOutputParser()

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

# 4. The Main Agent Function
def run_rag_agent(question: str, history_str: str):
    """Takes a question and chat history, searches vectors, and returns the AI answer."""
    expanded_search = f"{question} (Context: Moroccan Customs Administration, ADII, trade procedures)"
    docs = retriever.invoke(expanded_search)
    
    answer = chain.invoke({
        "context": format_docs(docs),
        "chat_history": history_str,
        "input": question
    })
    
    unique_sources = list(set([doc.metadata.get('source', 'Unknown') for doc in docs]))
    return answer, unique_sources