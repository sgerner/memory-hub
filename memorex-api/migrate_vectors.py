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

print("Async Embedding Worker started.")

POSTGRES_DB = os.getenv("POSTGRES_DB", "agentmemory")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "memory-db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3-embedding:4b")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2").strip()
GEMINI_OUTPUT_DIMENSIONALITY = int(os.getenv("GEMINI_OUTPUT_DIMENSIONALITY", os.getenv("EMBEDDING_DIMS", "2560")))
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/embedding-worker.json")

BATCH_SIZE = int(os.getenv("MIGRATION_BATCH_SIZE", "1000"))
CONCURRENCY = int(os.getenv("MIGRATION_CONCURRENCY", "1"))
GEMINI_CONCURRENCY = int(os.getenv("GEMINI_CONCURRENCY", str(max(1, CONCURRENCY))))
STATUS_UPDATE_EVERY = int(os.getenv("MIGRATION_STATUS_UPDATE_EVERY", "1"))
EMBED_CHUNK_SIZE = int(os.getenv("EMBED_CHUNK_SIZE", "1500"))
EMBED_CHUNK_OVERLAP = int(os.getenv("EMBED_CHUNK_OVERLAP", "150"))
EMBED_RETRY_MIN_CHUNK = int(os.getenv("EMBED_RETRY_MIN_CHUNK", "256"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))
GEMINI_RETRY_SLEEP_SECONDS = float(os.getenv("GEMINI_RETRY_SLEEP_SECONDS", "2"))
INTERNAL_CONTROL_COLUMNS = {
    "embedding_source_text": "TEXT",
    "embedding_status": "TEXT",
    "embedding_queued_at": "TEXT",
    "embedding_started_at": "TEXT",
    "embedding_finished_at": "TEXT",
    "embedding_available_at": "TEXT",
    "embedding_attempts": "INTEGER DEFAULT 0",
    "embedding_error": "TEXT",
}


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


def ensure_tracking_columns(conn, table_name: str):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table_name,))
        existing = {row["column_name"] for row in cur.fetchall()}
        for column_name, column_type in INTERNAL_CONTROL_COLUMNS.items():
            if column_name not in existing:
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                existing.add(column_name)
    conn.commit()


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
            if EMBEDDING_PROVIDER == "gemini":
                if not GEMINI_API_KEY:
                    print("GEMINI_API_KEY is missing while EMBEDDING_PROVIDER=gemini")
                    return None
                async with session.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_EMBED_MODEL}:embedContent",
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": GEMINI_API_KEY,
                    },
                    json={
                        "model": f"models/{GEMINI_EMBED_MODEL}",
                        "content": {"parts": [{"text": chunk}]},
                        "output_dimensionality": GEMINI_OUTPUT_DIMENSIONALITY,
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        vector = []
                        if isinstance(data.get("embedding"), dict):
                            vector = data.get("embedding", {}).get("values", []) or []
                        if not vector and isinstance(data.get("embeddings"), list) and data["embeddings"]:
                            vector = (data["embeddings"][0] or {}).get("values", []) or []
                        if vector:
                            vectors.append(vector)
                        continue
                    body = await response.text()
                    if response.status == 429:
                        print(f"Gemini rate limited: {body}")
                        return None
                    print(f"Gemini error {response.status}: {body}")
                    return None
            else:
                async with session.post(
                    f"{OLLAMA_HOST}/api/embeddings",
                    json={"model": DEFAULT_MODEL, "prompt": chunk},
                    timeout=REQUEST_TIMEOUT_SECONDS,
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


async def process_row(session, table_name, row, conn, db_lock):
    embedding_text = row.get("embedding_source_text") or row["document"]
    emb = await get_embedding(session, embedding_text)
    now_str = str(time.time())
    if emb:
        emb_str = f"[{','.join(map(str, emb))}]"
        async with db_lock:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {table_name}
                    SET embedding = %s,
                        embedding_status = 'done',
                        embedding_finished_at = %s,
                        embedding_error = NULL,
                        embedding_available_at = NULL
                    WHERE id = %s
                    """,
                    (emb_str, now_str, row["id"]),
                )
            conn.commit()
        return True

    failure_message = "Failed to generate embedding."
    retry_after = str(time.time() + min(3600, max(60, 30 * max(1, int(row.get("embedding_attempts") or 1)))))
    async with db_lock:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {table_name}
                SET embedding_status = 'retry',
                    embedding_error = %s,
                    embedding_available_at = %s,
                    embedding_finished_at = %s
                WHERE id = %s
                """,
                (failure_message, retry_after, now_str, row["id"]),
            )
        conn.commit()
    return False


async def migrate_table(category):
    table_name = f"memory_{category}"
    print(f"\n--- Processing {table_name} ---")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
            if not cur.fetchone()["to_regclass"]:
                save_status(
                    {
                        "service": "embedding-worker",
                        "status": "idle",
                        "current_table": table_name,
                        "items_total": 0,
                        "items_processed": 0,
                        "items_remaining": 0,
                        "updated_at": utc_now(),
                    }
                )
                return 0

        ensure_tracking_columns(conn, table_name)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) as count
                FROM {table_name}
                WHERE embedding IS NULL
                   OR COALESCE(embedding_status, 'pending') IN ('pending', 'retry')
                   OR (
                       embedding_status = 'processing'
                       AND CAST(COALESCE(NULLIF(embedding_started_at, ''), '0') AS DOUBLE PRECISION) < EXTRACT(EPOCH FROM NOW()) - 3600
                   )
                """
            )
            total_todo = cur.fetchone()['count']
            print(f"Found {total_todo} records needing embeddings.")

            if total_todo == 0:
                save_status(
                    {
                        "service": "embedding-worker",
                        "status": "idle",
                        "current_table": table_name,
                        "items_total": 0,
                        "items_processed": 0,
                        "items_remaining": 0,
                        "last_success_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                )
                return 0

            started_at = str(time.time())
            cur.execute(
                f"""
                WITH claimed AS (
                    SELECT id, document, embedding_source_text
                    FROM {table_name}
                    WHERE (
                        embedding IS NULL
                        OR COALESCE(embedding_status, 'pending') IN ('pending', 'retry')
                        OR (
                            embedding_status = 'processing'
                            AND CAST(COALESCE(NULLIF(embedding_started_at, ''), '0') AS DOUBLE PRECISION) < EXTRACT(EPOCH FROM NOW()) - 3600
                        )
                    )
                      AND CAST(COALESCE(NULLIF(embedding_available_at, ''), '0') AS DOUBLE PRECISION) <= EXTRACT(EPOCH FROM NOW())
                    ORDER BY id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE {table_name} t
                SET embedding_status = 'processing',
                    embedding_started_at = %s,
                    embedding_attempts = COALESCE(embedding_attempts, 0) + 1,
                    embedding_error = NULL
                FROM claimed
                WHERE t.id = claimed.id
                RETURNING t.id,
                          claimed.document,
                          claimed.embedding_source_text,
                          COALESCE(t.embedding_attempts, 0) AS embedding_attempts
                """,
                (min(BATCH_SIZE, total_todo), started_at),
            )
            rows = cur.fetchall()
            conn.commit()

        if not rows:
            provider_concurrency = GEMINI_CONCURRENCY if EMBEDDING_PROVIDER == "gemini" else CONCURRENCY
            save_status(
                {
                    "service": "embedding-worker",
                    "status": "waiting",
                    "current_table": table_name,
                    "items_total": total_todo,
                    "items_processed": 0,
                    "items_remaining": total_todo,
                    "updated_at": utc_now(),
                    "details": {
                        "batch_size": 0,
                        "concurrency": max(1, provider_concurrency),
                        "completed_in_batch": 0,
                        "successful_in_batch": 0,
                    },
                }
            )
            return 0

        save_status(
            {
                "service": "embedding-worker",
                "status": "running",
                "current_table": table_name,
                "items_total": total_todo,
                "items_processed": total_todo - len(rows),
                "items_remaining": len(rows),
                "updated_at": utc_now(),
                "details": {
                    "batch_size": len(rows),
                    "concurrency": max(1, GEMINI_CONCURRENCY if EMBEDDING_PROVIDER == "gemini" else CONCURRENCY),
                    "completed_in_batch": 0,
                    "successful_in_batch": 0,
                },
            }
        )

        async with aiohttp.ClientSession() as session:
            provider_concurrency = GEMINI_CONCURRENCY if EMBEDDING_PROVIDER == "gemini" else CONCURRENCY
            print(f"Generating embeddings for batch of {len(rows)} with concurrency {max(1, provider_concurrency)}...")
            semaphore = asyncio.Semaphore(max(1, provider_concurrency))
            status_lock = asyncio.Lock()
            db_lock = asyncio.Lock()
            completed_in_batch = 0
            successful_in_batch = 0

            async def throttled_process(row):
                nonlocal completed_in_batch, successful_in_batch
                async with semaphore:
                    result = await process_row(session, table_name, row, conn, db_lock)

                async with status_lock:
                    completed_in_batch += 1
                    if result:
                        successful_in_batch += 1
                    if completed_in_batch % STATUS_UPDATE_EVERY == 0 or completed_in_batch == len(rows):
                        save_status(
                            {
                                "service": "embedding-worker",
                                "status": "running",
                                "current_table": table_name,
                                "items_total": total_todo,
                                "items_processed": (total_todo - len(rows)) + successful_in_batch,
                                "items_remaining": max(0, len(rows) - successful_in_batch),
                                "last_success_at": utc_now() if successful_in_batch else None,
                                "updated_at": utc_now(),
                                "details": {
                                    "batch_size": len(rows),
                                    "concurrency": max(1, provider_concurrency),
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
                    "service": "embedding-worker",
                    "status": "running",
                    "current_table": table_name,
                    "items_total": total_todo,
                    "items_processed": total_todo - len(rows) + success_count,
                    "items_remaining": max(0, total_todo - (total_todo - len(rows) + success_count)),
                    "last_success_at": utc_now() if success_count else None,
                    "updated_at": utc_now(),
                    "details": {
                        "batch_size": len(rows),
                        "concurrency": max(1, provider_concurrency),
                    },
                }
            )
            return success_count

    except Exception as exc:
        print(f"Error in table {table_name}: {exc}")
        save_status(
            {
                "service": "embedding-worker",
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
                "service": "embedding-worker",
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
        due_left = False
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                for category in categories:
                    table_name = f"memory_{category}"
                    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
                    if not cur.fetchone()["to_regclass"]:
                        continue
                    cur.execute(
                        f"""
                        SELECT
                            COUNT(*) AS total_count,
                            COUNT(*) FILTER (
                                WHERE CAST(COALESCE(NULLIF(embedding_available_at, ''), '0') AS DOUBLE PRECISION) <= EXTRACT(EPOCH FROM NOW())
                                   OR (
                                       embedding_status = 'processing'
                                       AND CAST(COALESCE(NULLIF(embedding_started_at, ''), '0') AS DOUBLE PRECISION) < EXTRACT(EPOCH FROM NOW()) - 3600
                                   )
                            ) AS due_count
                        FROM {table_name}
                        WHERE embedding IS NULL
                           OR COALESCE(embedding_status, 'pending') IN ('pending', 'retry', 'processing')
                        """
                    )
                    counts = cur.fetchone()
                    if counts["total_count"] > 0:
                        any_left = True
                    if counts["due_count"] > 0:
                        due_left = True
        finally:
            conn.close()

        if not any_left:
            finished_at = utc_now()
            print("No more items to migrate. Exiting.")
            save_status(
                {
                    "service": "embedding-worker",
                    "status": "idle",
                    "current_table": None,
                    "items_processed": total_processed,
                    "items_remaining": 0,
                    "last_success_at": finished_at,
                    "updated_at": finished_at,
                }
            )
            break

        sleep_seconds = 5 if due_left else 30
        print(f"Completed a cycle. Starting next batch in {sleep_seconds}s...")
        save_status(
            {
                "service": "embedding-worker",
                "status": "running",
                "current_table": None,
                "items_processed": total_processed,
                "items_remaining": None,
                "updated_at": utc_now(),
            }
        )
        await asyncio.sleep(sleep_seconds)


if __name__ == "__main__":
    asyncio.run(main())
