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
print(f"Tables: {tables}")

if tables:
    table = tables[0][0]
    print(f"Using table: {table}")
    
    # Try EXPLAIN ANALYZE on current query structure
    emb = "[0.0]" * 2560 # just dummy zero vector for plan
    emb_str = "[" + ",".join(["0"] * 2560) + "]"
    
    current_query = f"""
        EXPLAIN ANALYZE SELECT id, document,
               embedding::halfvec(2560) <=> CAST(%s AS halfvec(2560)) AS distance
        FROM {table} t
        ORDER BY distance ASC
        LIMIT 10
    """
    try:
        cur.execute(current_query, [emb_str])
        print("--- Current Query Plan ---")
        for row in cur.fetchall():
            print(row[0])
    except Exception as e:
        print(f"Error: {e}")

    # Try EXPLAIN ANALYZE on optimized query structure
    optimized_query = f"""
        EXPLAIN ANALYZE SELECT id, document,
               embedding::halfvec(2560) <=> CAST(%s AS halfvec(2560)) AS distance
        FROM {table} t
        ORDER BY embedding::halfvec(2560) <=> CAST(%s AS halfvec(2560)) ASC
        LIMIT 10
    """
    try:
        cur.execute(optimized_query, [emb_str, emb_str])
        print("--- Optimized Query Plan ---")
        for row in cur.fetchall():
            print(row[0])
    except Exception as e:
        print(f"Error: {e}")

cur.close()
conn.close()
