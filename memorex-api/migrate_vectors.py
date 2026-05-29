import asyncio
import json
import os
import math
import time
from datetime import datetime, timezone
from typing import List

import aiohttp
import psycopg2
from psycopg2.extras import RealDictCursor

print("Async Migration Script started.")

POSTGRES_DB = os.getenv("POSTGRES_DB", "agentmemory")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "memory-db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3-embedding:4b")
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/migration-worker.json")

BATCH_SIZE = int(os.getenv("MIGRATION_BATCH_SIZE", "1000"))
CONCURRENCY = int(os.getenv("MIGRATION_CONCURRENCY", "4"))
STATUS_UPDATE_EVERY = int(os.getenv("MIGRATION_STATUS_UPDATE_EVERY", "1"))
EMBED_CHUNK_SIZE = int(os.getenv("EMBED_CHUNK_SIZE", "1500"))
EMBED_CHUNK_OVERLAP = int(os.getenv("EMBED_CHUNK_OVERLAP", "150"))
EMBED_RETRY_MIN_CHUNK = int(os.getenv("EMBED_RETRY_MIN_CHUNK", "256"))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_status(status):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    temp_path = f"{STATUS_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(status, handle)
    os.replace(temp_path, STATUS_PATH)


def get_db_connection():
    return psycopg2.connect(
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        cursor_factory=RealDictCursor,
    )


def split_embedding_text(text: str, chunk_size: int = EMBED_CHUNK_SIZE, overlap: int = EMBED_CHUNK_OVERLAP) -> List[str]:
    cleaned = str(text).replace("\x00", "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: List[str] = []
    start = 0
    text_length = len(cleaned)
    while start < text_length:
        end = min(text_length, start + chunk_size)
        if end < text_length:
            break_point = -1
            for separator in ("\n\n", "\n", " "):
                candidate = cleaned.rfind(separator, start, end)
                if candidate > break_point:
                    break_point = candidate
            if break_point > start + chunk_size // 2:
                end = break_point

        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break
        start = max(0, end - overlap)
        if start >= text_length:
            break

    return chunks or [cleaned[:chunk_size]]


def average_embeddings(vectors: List[List[float]]) -> List[float]:
    usable = [vector for vector in vectors if vector]
    if not usable:
        return []
    if len(usable) == 1:
        return usable[0]

    width = len(usable[0])
    totals = [0.0] * width
    count = 0
    for vector in usable:
        if len(vector) != width:
            continue
        for index, value in enumerate(vector):
            totals[index] += float(value)
        count += 1

    if count == 0:
        return []

    averaged = [value / count for value in totals]
    norm = math.sqrt(sum(value * value for value in averaged))
    if norm > 0:
        averaged = [value / norm for value in averaged]
    return averaged


async def get_embedding(session, text):
    try:
        chunks = split_embedding_text(text)
        if not chunks:
            return None

        vectors = []
        for chunk in chunks:
            async with session.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": DEFAULT_MODEL, "prompt": chunk},
                timeout=120,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    vector = data.get("embedding", [])
                    if vector:
                        vectors.append(vector)
                    continue

                body = await response.text()
                if "context length" in body.lower() and len(chunk) > EMBED_RETRY_MIN_CHUNK:
                    smaller_size = max(EMBED_RETRY_MIN_CHUNK, len(chunk) // 2)
                    nested_vectors = []
                    for sub_chunk in split_embedding_text(
                        chunk,
                        smaller_size,
                        max(EMBED_CHUNK_OVERLAP // 2, 50),
                    ):
                        sub_vector = await get_embedding(session, sub_chunk)
                        if sub_vector:
                            nested_vectors.append(sub_vector)
                    return average_embeddings(nested_vectors)

                print(f"Ollama error {response.status}: {body}")
                return None

        return average_embeddings(vectors)
    except Exception as exc:
        print(f"Ollama connection error: {exc}")
        return None


async def process_row(session, table_name, row, conn):
    emb = await get_embedding(session, row['document'])
    if emb:
        emb_str = f"[{','.join(map(str, emb))}]"
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {table_name} SET embedding = %s WHERE id = %s", (emb_str, row['id']))
        conn.commit()
        return True
    return False


async def migrate_table(category):
    table_name = f"memory_{category}"
    print(f"\n--- Processing {table_name} ---")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) as count FROM {table_name} WHERE embedding IS NULL")
            total_todo = cur.fetchone()['count']
            print(f"Found {total_todo} records needing embeddings.")

            if total_todo == 0:
                save_status(
                    {
                        "service": "migration-worker",
                        "status": "idle",
                        "current_table": table_name,
                        "items_total": 0,
                        "items_processed": 0,
                        "items_remaining": 0,
                        "last_success_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                )
                return

            cur.execute(
                f"SELECT id, document FROM {table_name} WHERE embedding IS NULL ORDER BY id ASC LIMIT %s",
                (min(BATCH_SIZE, total_todo),),
            )
            rows = cur.fetchall()

        save_status(
            {
                "service": "migration-worker",
                "status": "running",
                "current_table": table_name,
                "items_total": total_todo,
                "items_processed": total_todo - len(rows),
                "items_remaining": len(rows),
                "updated_at": utc_now(),
                "details": {
                    "batch_size": len(rows),
                    "concurrency": CONCURRENCY,
                    "completed_in_batch": 0,
                    "successful_in_batch": 0,
                },
            }
        )

        print(f"Generating embeddings for batch of {len(rows)} with concurrency {CONCURRENCY}...")

        async with aiohttp.ClientSession() as session:
            semaphore = asyncio.Semaphore(CONCURRENCY)
            status_lock = asyncio.Lock()
            completed_in_batch = 0
            successful_in_batch = 0

            async def throttled_process(row):
                nonlocal completed_in_batch, successful_in_batch
                async with semaphore:
                    result = await process_row(session, table_name, row, conn)

                async with status_lock:
                    completed_in_batch += 1
                    if result:
                        successful_in_batch += 1
                    if completed_in_batch % STATUS_UPDATE_EVERY == 0 or completed_in_batch == len(rows):
                        save_status(
                            {
                                "service": "migration-worker",
                                "status": "running",
                                "current_table": table_name,
                                "items_total": total_todo,
                                "items_processed": (total_todo - len(rows)) + successful_in_batch,
                                "items_remaining": max(0, len(rows) - successful_in_batch),
                                "last_success_at": utc_now() if successful_in_batch else None,
                                "updated_at": utc_now(),
                                "details": {
                                    "batch_size": len(rows),
                                    "concurrency": CONCURRENCY,
                                    "completed_in_batch": completed_in_batch,
                                    "successful_in_batch": successful_in_batch,
                                },
                            }
                        )
                return result

            tasks = [throttled_process(row) for row in rows]
            results = await asyncio.gather(*tasks)

            success_count = sum(1 for result in results if result)
            print(f"Batch complete. Success: {success_count}/{len(rows)}")
            save_status(
                {
                    "service": "migration-worker",
                    "status": "running",
                    "current_table": table_name,
                    "items_total": total_todo,
                    "items_processed": success_count,
                    "items_remaining": max(0, total_todo - success_count),
                    "last_success_at": utc_now() if success_count else None,
                    "updated_at": utc_now(),
                    "details": {
                        "batch_size": len(rows),
                        "concurrency": CONCURRENCY,
                    },
                }
            )
            return success_count

    except Exception as exc:
        print(f"Error in table {table_name}: {exc}")
        save_status(
            {
                "service": "migration-worker",
                "status": "error",
                "current_table": table_name,
                "last_error": str(exc),
                "updated_at": utc_now(),
            }
        )
        return 0
    finally:
        conn.close()


async def main():
    while True:
        categories = ["emails", "documents", "obsidian", "code"]
        total_processed = 0

        save_status(
            {
                "service": "migration-worker",
                "status": "running",
                "current_table": None,
                "items_total": None,
                "items_processed": total_processed,
                "items_remaining": None,
                "updated_at": utc_now(),
            }
        )

        for category in categories:
            total_processed += await migrate_table(category)

        any_left = False
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                for category in categories:
                    cur.execute(f"SELECT COUNT(*) as count FROM memory_{category} WHERE embedding IS NULL")
                    if cur.fetchone()['count'] > 0:
                        any_left = True
                        break
        finally:
            conn.close()

        if not any_left:
            finished_at = utc_now()
            print("No more items to migrate. Exiting.")
            save_status(
                {
                    "service": "migration-worker",
                    "status": "idle",
                    "current_table": None,
                    "items_processed": total_processed,
                    "items_remaining": 0,
                    "last_success_at": finished_at,
                    "updated_at": finished_at,
                }
            )
            break

        print("Completed a cycle. Starting next batch in 5s...")
        save_status(
            {
                "service": "migration-worker",
                "status": "running",
                "current_table": None,
                "items_processed": total_processed,
                "items_remaining": None,
                "updated_at": utc_now(),
            }
        )
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
