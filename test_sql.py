from sql_agent import run_sql_agent

print("🤖 Welcome to the SQL Agent Tester!")
print("Connecting to Enterprise Database...\n")

# You can change this question to test different tables!
question = "What is the import duty for HS code 8501?"

print(f"👤 Question: {question}")
print("-" * 50)

# Run the agent
answer = run_sql_agent(question)

print("-" * 50)
print(f"✨ AI Answer: {answer}")