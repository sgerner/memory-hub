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

# Get a category that exists and has rows
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_name = 'memory_emails'")
tables = cur.fetchall()

if tables:
    table = tables[0][0]
    print(f"Using table: {table}")

    # Check if cols exist
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='account'", (table,))
    if cur.fetchone():
        try:
            # Drop the index if it exists to test without it
            cur.execute(f"DROP INDEX IF EXISTS {table}_account_message_id_idx")
            print("--- Query without Index ---")
            cur.execute(f"EXPLAIN ANALYZE SELECT id FROM {table} WHERE account = 'test@example.com' AND message_id = '<12345@example.com>' ORDER BY id DESC LIMIT 1")
            for row in cur.fetchall():
                print(row[0])
            
            # Create index
            print("Creating index...")
            cur.execute(f"CREATE INDEX {table}_account_message_id_idx ON {table} (account, message_id)")
            
            print("--- Query with Index ---")
            cur.execute(f"EXPLAIN ANALYZE SELECT id FROM {table} WHERE account = 'test@example.com' AND message_id = '<12345@example.com>' ORDER BY id DESC LIMIT 1")
            for row in cur.fetchall():
                print(row[0])
        except Exception as e:
            print(f"Error: {e}")
else:
    print("Table memory_emails not found.")

cur.close()
conn.close()
