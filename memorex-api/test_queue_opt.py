import os
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    dbname="agentmemory",
    user="admin",
    password="memory-vault-secure-pass",
    host="memory-db",
    port=5432
)
conn.autocommit = True

cur = conn.cursor()
cur.execute("SET enable_seqscan = off;")

# Get a category that exists and has rows
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'memory_%'")
tables = cur.fetchall()

if tables:
    table = tables[0][0]
    print(f"Using table: {table}")
    
    current_query = f"""
        EXPLAIN ANALYZE SELECT COUNT(*) AS count FROM {table} WHERE embedding IS NULL OR COALESCE(LOWER(embedding_status), 'pending') IN ('pending', 'retry', 'processing')
    """
    try:
        cur.execute(current_query)
        print("--- Current Query Plan ---")
        for row in cur.fetchall():
            print(row[0])
    except Exception as e:
        print(f"Error: {e}")

    optimized_query = f"""
        EXPLAIN ANALYZE SELECT COUNT(*) AS count FROM {table} WHERE embedding IS NULL OR LOWER(embedding_status) IN ('pending', 'retry', 'processing') OR embedding_status IS NULL
    """
    try:
        cur.execute(optimized_query)
        print("--- Optimized Query Plan ---")
        for row in cur.fetchall():
            print(row[0])
    except Exception as e:
        print(f"Error: {e}")

cur.close()
conn.close()
