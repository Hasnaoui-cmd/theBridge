import os
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_postgres import PGVector

# 1. Load Environment Variables
load_dotenv()
db_url = os.getenv("DATABASE_URL")
# Fix the URL for the Langchain Postgres driver
connection_string = db_url.replace("postgresql://", "postgresql+psycopg://")

# 2. Connect to the LOCAL Chroma Database
CHROMA_PATH = "./chroma_db_llama"
print("1️⃣ Booting up Local ChromaDB...")
embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
local_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_model)

# 3. Extract EVERYTHING from Chroma
print("2️⃣ Extracting raw vectors and documents from ChromaDB...")
# We explicitly ask Chroma to give us the mathematical embeddings
chroma_data = local_db.get(include=["embeddings", "documents", "metadatas"])

documents = chroma_data["documents"]
embeddings = chroma_data["embeddings"]
metadatas = chroma_data["metadatas"]
ids = chroma_data["ids"]

print(f"   -> Successfully extracted {len(documents)} chunks from local storage!")

# 4. Connect to the CLOUD Supabase Database
print("3️⃣ Connecting to Supabase PostgreSQL...")
cloud_db = PGVector(
    embeddings=embedding_model,
    collection_name="documents", 
    connection=connection_string,
    use_jsonb=True,
)

# 5. Direct Injection
print("4️⃣ Injecting vectors directly into Supabase...")

# The new LangChain Postgres driver wants them as separate lists!
cloud_db.add_embeddings(
    texts=documents,
    embeddings=embeddings,
    metadatas=metadatas,
    ids=ids
)

print("✅ DIRECT MIGRATION COMPLETE! Your AI Brain is officially in the Cloud! ☁️")