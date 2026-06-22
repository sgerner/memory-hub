import os
import time
import json
import logging
import traceback
import re
import math
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
import requests

# Configuration
POSTGRES_DB = os.getenv("POSTGRES_DB", "agentmemory")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "memory-db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3-embedding:4b")
VERCEL_API_KEY = os.getenv("VERCEL_API_KEY", "")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "2560"))
HNSW_EF_SEARCH = int(os.getenv("VECTOR_INDEX_EF_SEARCH", "100"))
SEARCH_VECTOR_WEIGHT = float(os.getenv("SEARCH_VECTOR_WEIGHT", "0.72"))
SEARCH_TEXT_WEIGHT = float(os.getenv("SEARCH_TEXT_WEIGHT", "0.28"))
SEARCH_LEXICAL_MULTIPLIER = int(os.getenv("SEARCH_LEXICAL_MULTIPLIER", "4"))
SEARCH_LEXICAL_TIMEOUT_MS = int(os.getenv("SEARCH_LEXICAL_TIMEOUT_MS", "800"))
SEARCH_LEXICAL_MAX_CHARS = int(os.getenv("SEARCH_LEXICAL_MAX_CHARS", "50000"))
EMBED_CACHE_TTL_SECONDS = int(os.getenv("EMBED_CACHE_TTL_SECONDS", "3600"))
EMBED_CACHE_MAX_ITEMS = int(os.getenv("EMBED_CACHE_MAX_ITEMS", "512"))
LEXICAL_INDEX_CATEGORIES = {
    item.strip()
    for item in os.getenv("LEXICAL_INDEX_CATEGORIES", "agent,emails,obsidian,documents").split(",")
    if item.strip()
}
LEXICAL_STOP_WORDS = {
    "about",
    "after",
    "and",
    "api",
    "are",
    "but",
    "can",
    "config",
    "configuration",
    "credential",
    "credentials",
    "decision",
    "decisions",
    "did",
    "for",
    "from",
    "how",
    "into",
    "key",
    "keys",
    "not",
    "our",
    "password",
    "the",
    "then",
    "secret",
    "secrets",
    "this",
    "token",
    "tokens",
    "was",
    "what",
    "when",
    "where",
    "with",
}
AUTH_TOKEN = os.environ["AGENTMEMORY_TOKEN"].strip()
ALLOWED_CATEGORIES = {
    item.strip()
    for item in os.getenv("MEMORY_CATEGORIES", "agent,emails,obsidian,documents,code").split(",")
    if item.strip()
}
SAFE_CATEGORY = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
INTERNAL_METADATA_KEYS = [
    "embedding_source_text",
    "embedding_status",
    "embedding_queued_at",
    "embedding_started_at",
    "embedding_finished_at",
    "embedding_available_at",
    "embedding_attempts",
    "embedding_error",
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Memorex Core API")

EMBED_CHUNK_SIZE = int(os.getenv("EMBED_CHUNK_SIZE", "1500"))
EMBED_CHUNK_OVERLAP = int(os.getenv("EMBED_CHUNK_OVERLAP", "150"))
EMBED_RETRY_MIN_CHUNK = int(os.getenv("EMBED_RETRY_MIN_CHUNK", "256"))
OLLAMA_EMBED_TIMEOUT = int(os.getenv("OLLAMA_EMBED_TIMEOUT", "120"))
embedding_cache_lock = threading.Lock()
embedding_cache: dict[str, tuple[float, List[float]]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

try:
    from sentence_transformers import CrossEncoder
    reranker_model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)
except Exception as e:
    logger.warning(f"Failed to load cross-encoder: {e}")
    reranker_model = None

def rerank_candidates(query_text: str, candidates: list[Dict[str, Any]], limit: int) -> list[Dict[str, Any]]:
    if not reranker_model or not candidates:
        return candidates[:limit]
    pairs = [(query_text, str(cand.get("document", ""))) for cand in candidates]
    try:
        scores = reranker_model.predict(pairs)
        for cand, score in zip(candidates, scores):
            cand["cross_encoder_score"] = float(score)
        candidates.sort(key=lambda item: item.get("cross_encoder_score", -9999), reverse=True)
    except Exception as e:
        logger.error(f"Error during reranking: {e}")
    return candidates[:limit]


def ensure_vector_indexes():
    try:
        with get_db_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_prewarm")
                for category in sorted(ALLOWED_CATEGORIES):
                    table_name = table_for(category)
                    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
                    if not cur.fetchone()["to_regclass"]:
                        continue

                    existing_cols = existing_columns(cur, table_name)

                    if category == "emails" and {"account", "folder", "uid"}.issubset(existing_cols):
                        email_index_name = f"{table_name}_account_folder_uid_idx"
                        cur.execute("SELECT to_regclass(%s)", (f"public.{email_index_name}",))
                        if not cur.fetchone()["to_regclass"]:
                            logger.info("Creating email lookup index %s on %s", email_index_name, table_name)
                            cur.execute(f"CREATE INDEX CONCURRENTLY {email_index_name} ON {table_name} (account, folder, uid)")
                            logger.info("Email lookup index ready: %s", email_index_name)

                    if category == "emails" and {"account", "message_id"}.issubset(existing_cols):
                        email_msg_index_name = f"{table_name}_account_message_id_idx"
                        cur.execute("SELECT to_regclass(%s)", (f"public.{email_msg_index_name}",))
                        if not cur.fetchone()["to_regclass"]:
                            logger.info("Creating email message_id lookup index %s on %s", email_msg_index_name, table_name)
                            cur.execute(f"CREATE INDEX CONCURRENTLY {email_msg_index_name} ON {table_name} (account, message_id)")
                            logger.info("Email message_id lookup index ready: %s", email_msg_index_name)

                    operational_indexes: list[tuple[str, str]] = []
                    if "embedding_status" in existing_cols:
                        operational_indexes.append(
                            (
                                f"{table_name}_embedding_status_available_idx",
                                f"CREATE INDEX CONCURRENTLY {{name}} ON {table_name} (lower(embedding_status), embedding_available_at, id)",
                            )
                        )
                    if "embedding" in existing_cols:
                        operational_indexes.append(
                            (
                                f"{table_name}_embedding_missing_idx",
                                f"CREATE INDEX CONCURRENTLY {{name}} ON {table_name} (id) WHERE embedding IS NULL",
                            )
                        )
                    if "needs_enrichment" in existing_cols:
                        operational_indexes.append(
                            (
                                f"{table_name}_needs_enrichment_id_idx",
                                f"CREATE INDEX CONCURRENTLY {{name}} ON {table_name} (LOWER(needs_enrichment), id DESC)",
                            )
                        )
                    if "lifecycle_status" in existing_cols:
                        operational_indexes.append(
                            (
                                f"{table_name}_lifecycle_status_id_idx",
                                f"CREATE INDEX CONCURRENTLY {{name}} ON {table_name} (lifecycle_status, id DESC)",
                            )
                        )

                    for index_name, create_sql in operational_indexes:
                        cur.execute("SELECT to_regclass(%s)", (f"public.{index_name}",))
                        if not cur.fetchone()["to_regclass"]:
                            logger.info("Creating operational index %s on %s", index_name, table_name)
                            cur.execute(create_sql.format(name=index_name))
                            logger.info("Operational index ready: %s", index_name)

                    index_name = f"{table_name}_embedding_halfvec_hnsw_idx"
                    cur.execute("SELECT to_regclass(%s)", (f"public.{index_name}",))
                    if not cur.fetchone()["to_regclass"]:
                        logger.info("Creating vector index %s on %s", index_name, table_name)
                        cur.execute(
                            f"CREATE INDEX CONCURRENTLY {index_name} ON {table_name} USING hnsw ((embedding::halfvec({EMBEDDING_DIMS})) halfvec_cosine_ops) WITH (m=32, ef_construction=128)"
                        )
                        logger.info("Vector index ready: %s", index_name)

                    # Prewarm the vector index
                    try:
                        cur.execute("SELECT pg_prewarm(%s)", (index_name,))
                        logger.info("Prewarmed vector index: %s", index_name)
                    except Exception as pwe:
                        logger.warning("Failed to prewarm index %s: %s", index_name, pwe)

                    if category not in LEXICAL_INDEX_CATEGORIES:
                        continue
                    lexical_index_name = f"{table_name}_document_50k_simple_tsv_idx"
                    cur.execute(
                        """
                        SELECT i.indisvalid AND i.indisready AS ready
                        FROM pg_index i
                        JOIN pg_class c ON c.oid = i.indexrelid
                        WHERE c.relname = %s
                        """,
                        (lexical_index_name,),
                    )
                    lexical_status = cur.fetchone()
                    if lexical_status and not lexical_status["ready"]:
                        logger.info("Dropping invalid lexical index %s on %s", lexical_index_name, table_name)
                        cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {lexical_index_name}")
                        lexical_status = None
                    if not lexical_status:
                        logger.info("Creating lexical index %s on %s", lexical_index_name, table_name)
                        cur.execute(
                            f"CREATE INDEX CONCURRENTLY {lexical_index_name} ON {table_name} USING gin (to_tsvector('simple', left(coalesce(document, ''), {SEARCH_LEXICAL_MAX_CHARS})))"
                        )
                        logger.info("Lexical index ready: %s", lexical_index_name)
    except Exception as exc:
        logger.error("Vector index bootstrap failed: %s", exc)


db_pool = None

@app.on_event("startup")
async def bootstrap_background_tasks():
    global db_pool
    db_pool = ThreadedConnectionPool(
        1, 50,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        cursor_factory=RealDictCursor
    )
    threading.Thread(target=ensure_vector_indexes, daemon=True).start()

@app.on_event("shutdown")
async def shutdown_db_pool():
    if db_pool:
        db_pool.closeall()

@contextmanager
def get_db_connection():
    conn = db_pool.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        db_pool.putconn(conn)

def split_embedding_text(text: str, chunk_size: int = EMBED_CHUNK_SIZE, overlap: int = EMBED_CHUNK_OVERLAP) -> List[str]:
    cleaned = str(text).replace('\x00', '').strip()
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


def request_embedding_chunk(text: str, chunk_size: int = EMBED_CHUNK_SIZE) -> List[float]:
    if VERCEL_API_KEY:
        try:
            vercel_resp = requests.post(
                "https://ai-gateway.vercel.sh/v1/embeddings",
                headers={"Authorization": f"Bearer {VERCEL_API_KEY}", "Content-Type": "application/json"},
                json={"input": text, "model": "alibaba/qwen3-embedding-4b"},
                timeout=OLLAMA_EMBED_TIMEOUT
            )
            if vercel_resp.status_code == 200:
                data = vercel_resp.json()
                if "data" in data and len(data["data"]) > 0:
                    return data["data"][0]["embedding"]
            else:
                logger.warning("Vercel Gateway failed (HTTP %s): %s. Falling back to local Ollama.", vercel_resp.status_code, vercel_resp.text)
        except Exception as e:
            logger.warning("Vercel Gateway error: %s. Falling back to local Ollama.", e)

    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": DEFAULT_MODEL, "prompt": text, "keep_alive": -1},
            timeout=OLLAMA_EMBED_TIMEOUT,
        )
        if response.status_code == 200:
            return response.json().get("embedding", [])

        body = response.text
        if "context length" in body.lower() and chunk_size > EMBED_RETRY_MIN_CHUNK:
            smaller_chunk = max(EMBED_RETRY_MIN_CHUNK, chunk_size // 2)
            sub_vectors = [request_embedding_chunk(chunk, smaller_chunk) for chunk in split_embedding_text(text, smaller_chunk, max(EMBED_CHUNK_OVERLAP // 2, 50))]
            return average_embeddings(sub_vectors)

        logger.error("Ollama error %s: %s", response.status_code, body)
        return []
    except Exception as exc:
        logger.error("Ollama embedding error: %s", exc)
        return []


def get_embedding(text: str) -> List[float]:
    chunks = split_embedding_text(text)
    if not chunks:
        return []
    vectors = [request_embedding_chunk(chunk) for chunk in chunks]
    return average_embeddings(vectors)

def get_cached_embedding(text: str) -> List[float]:
    key = str(text).replace("\x00", "").strip().lower()
    now = time.time()
    with embedding_cache_lock:
        cached = embedding_cache.get(key)
        if cached and now - cached[0] <= EMBED_CACHE_TTL_SECONDS:
            return cached[1]

    embedding = get_embedding(text)
    if not embedding:
        return []

    with embedding_cache_lock:
        if len(embedding_cache) >= EMBED_CACHE_MAX_ITEMS:
            oldest_key = min(embedding_cache, key=lambda item: embedding_cache[item][0])
            embedding_cache.pop(oldest_key, None)
        embedding_cache[key] = (now, embedding)
    return embedding

def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ")[1]
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")
    return token

class MemoryCreate(BaseModel):
    content: str
    category: str
    metadata: Optional[Dict[str, Any]] = None
    embedding_text: Optional[str] = None
    related_to: Optional[List[str]] = None

class FilterCriteria(BaseModel):
    key: str
    op: str
    value: Any

class SearchQuery(BaseModel):
    query: str
    category: str
    limit: Optional[int] = 10
    metadata: Optional[Dict[str, Any]] = None
    ef_search: Optional[int] = None
    filters: Optional[List[FilterCriteria]] = None
    recency_decay: Optional[float] = None

class MultiSearchQuery(BaseModel):
    query: str
    categories: Optional[List[str]] = None
    limit: Optional[int] = 10
    metadata: Optional[Dict[str, Any]] = None
    ef_search: Optional[int] = None
    filters: Optional[List[FilterCriteria]] = None
    recency_decay: Optional[float] = None

class MemoryUpdate(BaseModel):
    id: str
    category: str
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    embedding_text: Optional[str] = None
    related_to: Optional[List[str]] = None

class MemoryDelete(BaseModel):
    id: str
    category: str

class EmailDelete(BaseModel):
    account: str
    folder: Optional[str] = None
    uid: Optional[str] = None
    message_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    receiver: Optional[str] = None
    date: Optional[str] = None
    reason: Optional[str] = None

def table_for(category: str) -> str:
    if not SAFE_CATEGORY.fullmatch(category) or category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Category is not enabled: {category}")
    return f"memory_{category}"

def existing_columns(cur, table_name: str) -> set[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table_name,))
    return {row["column_name"] for row in cur.fetchall()}

def metadata_projection(alias: str = "t") -> str:
    excluded = ["id", "document", "embedding", *INTERNAL_METADATA_KEYS]
    quoted = ", ".join(f"'{item}'" for item in excluded)
    return f"to_jsonb({alias}) - ARRAY[{quoted}] AS metadata"

def safe_metadata_key(key: str) -> Optional[str]:
    safe_key = "".join([char for char in key if char.isalnum() or char == "_"]).lower()
    if not safe_key or safe_key in INTERNAL_METADATA_KEYS or safe_key in {"id", "document", "embedding"}:
        return None
    return safe_key

def build_metadata_where(metadata: Optional[Dict[str, Any]], filters: Optional[List[FilterCriteria]], existing_cols: set[str], alias: str = "t") -> tuple[str, list[str]]:
    where_clauses = []
    where_vals = []
    if metadata:
        for key, value in metadata.items():
            safe_key = safe_metadata_key(key)
            if safe_key in existing_cols:
                where_clauses.append(f"{alias}.{safe_key} = %s")
                where_vals.append(str(value))
    if filters:
        for f in filters:
            safe_key = safe_metadata_key(f.key)
            if safe_key in existing_cols:
                if f.op == "=":
                    where_clauses.append(f"{alias}.{safe_key} = %s")
                    where_vals.append(str(f.value))
                elif f.op == ">":
                    where_clauses.append(f"{alias}.{safe_key} > %s")
                    where_vals.append(str(f.value))
                elif f.op == ">=":
                    where_clauses.append(f"{alias}.{safe_key} >= %s")
                    where_vals.append(str(f.value))
                elif f.op == "<":
                    where_clauses.append(f"{alias}.{safe_key} < %s")
                    where_vals.append(str(f.value))
                elif f.op == "<=":
                    where_clauses.append(f"{alias}.{safe_key} <= %s")
                    where_vals.append(str(f.value))
                elif f.op == "!=":
                    where_clauses.append(f"{alias}.{safe_key} != %s")
                    where_vals.append(str(f.value))
                elif f.op.lower() in ("in", "contains"):
                    where_clauses.append(f"{alias}.{safe_key} ILIKE %s")
                    where_vals.append(f"%{f.value}%")
    return ("WHERE " + " AND ".join(where_clauses), where_vals) if where_clauses else ("", [])

def build_lexical_tsquery(query_text: str) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in re.findall(r"[A-Za-z0-9]+", query_text.lower()):
        if len(raw_term) < 3 or raw_term in LEXICAL_STOP_WORDS or raw_term in seen:
            continue
        seen.add(raw_term)
        terms.append(raw_term)
        if len(terms) >= 12:
            break
    return " | ".join(f"{term}:*" for term in terms)

def vector_score(distance: Any) -> float:
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, 1.0 - (value / 1.5)))

def text_score(rank: Any, max_rank: float) -> float:
    try:
        value = float(rank)
    except (TypeError, ValueError):
        return 0.0
    if max_rank <= 0:
        return 0.0
    return max(0.0, min(1.0, value / max_rank))

def combine_candidates(category: str, rows: list[Dict[str, Any]], limit: int, recency_decay: Optional[float] = None) -> list[Dict[str, Any]]:
    max_rank = max((float(row.get("lexical_rank") or 0) for row in rows), default=0.0)
    by_id: dict[str, Dict[str, Any]] = {}
    for row in rows:
        memory_id = str(row["id"])
        current = by_id.get(memory_id)
        if current is None:
            current = {
                "id": row["id"],
                "document": row["document"],
                "metadata": row["metadata"],
                "distance": row.get("distance"),
                "lexical_rank": float(row.get("lexical_rank") or 0),
                "category": category,
            }
            by_id[memory_id] = current
            continue
        if row.get("distance") is not None and (
            current.get("distance") is None or float(row["distance"]) < float(current["distance"])
        ):
            current["distance"] = row["distance"]
        current["lexical_rank"] = max(float(current.get("lexical_rank") or 0), float(row.get("lexical_rank") or 0))

    results = []
    now_ts = time.time()
    for row in by_id.values():
        score = (SEARCH_VECTOR_WEIGHT * vector_score(row.get("distance"))) + (
            SEARCH_TEXT_WEIGHT * text_score(row.get("lexical_rank"), max_rank)
        )
        if recency_decay and recency_decay > 0:
            created_at_str = row.get("metadata", {}).get("created_at") or row.get("metadata", {}).get("recorded_at")
            if created_at_str:
                try:
                    if "T" in str(created_at_str):
                        dt = datetime.fromisoformat(str(created_at_str).replace("Z", "+00:00"))
                        created_ts = dt.timestamp()
                    else:
                        created_ts = float(created_at_str)
                    age_days = (now_ts - created_ts) / 86400.0
                    if age_days > 0:
                        decay_multiplier = math.pow(0.5, age_days / recency_decay)
                        score = score * decay_multiplier
                except Exception:
                    pass
        row["score"] = score
        results.append(row)

    results.sort(key=lambda item: (-float(item.get("score") or 0), float(item.get("distance") or 99), -float(item.get("lexical_rank") or 0)))
    return results[:limit]

def search_category(cur, category: str, query_text: str, emb_str: str, limit: int, metadata: Optional[Dict[str, Any]], filters: Optional[List[FilterCriteria]] = None, recency_decay: Optional[float] = None) -> list[Dict[str, Any]]:
    table_name = table_for(category)
    cur.execute("SELECT to_regclass(%s)", (table_name,))
    if not cur.fetchone()["to_regclass"]:
        return []

    existing_cols = existing_columns(cur, table_name)
    where_sql, where_vals = build_metadata_where(metadata, filters, existing_cols)
    vector_limit = max(limit * 3, 20)
    lexical_limit = max(limit * SEARCH_LEXICAL_MULTIPLIER, 20)

    vector_query = f"""
        SELECT id, document,
               embedding::halfvec({EMBEDDING_DIMS}) <=> CAST(%s AS halfvec({EMBEDDING_DIMS})) AS distance,
               0.0::double precision AS lexical_rank,
               {metadata_projection('t')}
        FROM {table_name} t
        {where_sql}
        ORDER BY embedding::halfvec({EMBEDDING_DIMS}) <=> CAST(%s AS halfvec({EMBEDDING_DIMS})) ASC
        LIMIT %s
    """
    cur.execute(vector_query, [emb_str] + where_vals + [emb_str, vector_limit])
    rows = list(cur.fetchall())

    lexical_index_name = f"{table_name}_document_50k_simple_tsv_idx"
    cur.execute(
        """
        SELECT i.indisvalid AND i.indisready AS ready
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        WHERE c.relname = %s
        """,
        (lexical_index_name,),
    )
    index_status = cur.fetchone()
    if not index_status or not index_status["ready"]:
        return combine_candidates(category, rows, limit, recency_decay)

    lexical_tsquery = build_lexical_tsquery(query_text)
    if not lexical_tsquery:
        return combine_candidates(category, rows, limit, recency_decay)

    lexical_query = f"""
        SELECT id, document,
               NULL::double precision AS distance,
               ts_rank_cd(to_tsvector('simple', left(coalesce(document, ''), {SEARCH_LEXICAL_MAX_CHARS})), to_tsquery('simple', %s)) AS lexical_rank,
               {metadata_projection('t')}
        FROM {table_name} t
        {where_sql}
        {"AND" if where_sql else "WHERE"} to_tsquery('simple', %s) @@ to_tsvector('simple', left(coalesce(document, ''), {SEARCH_LEXICAL_MAX_CHARS}))
        ORDER BY lexical_rank DESC
        LIMIT %s
    """
    cur.execute("SAVEPOINT lexical_search")
    try:
        cur.execute(f"SET LOCAL statement_timeout = {SEARCH_LEXICAL_TIMEOUT_MS}")
        cur.execute(lexical_query, [lexical_tsquery] + where_vals + [lexical_tsquery, lexical_limit])
        rows.extend(cur.fetchall())
        cur.execute("SET LOCAL statement_timeout = 0")
        cur.execute("RELEASE SAVEPOINT lexical_search")
    except psycopg2.errors.QueryCanceled:
        cur.execute("ROLLBACK TO SAVEPOINT lexical_search")
        cur.execute("RELEASE SAVEPOINT lexical_search")
        logger.warning("Lexical search timed out for category=%s query=%r", category, query_text[:120])
    return combine_candidates(category, rows, limit, recency_decay)

def search_category_parallel(category: str, query_text: str, emb_str: str, limit: int, metadata: Optional[Dict[str, Any]], filters: Optional[List[FilterCriteria]] = None, recency_decay: Optional[float] = None, ef_search: Optional[int] = None) -> list[Dict[str, Any]]:
    started_at = time.time()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if ef_search is not None:
                cur.execute(f"SET hnsw.ef_search = {ef_search}")
            results = search_category(cur, category, query_text, emb_str, limit, metadata, filters, recency_decay)
    logger.info("Search category %s completed in %.2f ms", category, (time.time() - started_at) * 1000)
    return results


def _ensure_table(conn, category: str, metadata: Dict[str, Any]):
    table_name = table_for(category)
    with conn.cursor() as cur:
        # Create table if not exists
        cur.execute(f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                document TEXT NOT NULL,
                embedding vector({EMBEDDING_DIMS}),
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        
        # Check existing columns
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table_name,))
        existing_cols = {row['column_name'] for row in cur.fetchall()}

        control_columns = {
            "embedding_source_text": "TEXT",
            "embedding_status": "TEXT",
            "embedding_queued_at": "TEXT",
            "embedding_started_at": "TEXT",
            "embedding_finished_at": "TEXT",
            "embedding_available_at": "TEXT",
            "embedding_attempts": "INTEGER DEFAULT 0",
            "embedding_error": "TEXT",
        }
        for column_name, column_type in control_columns.items():
            if column_name not in existing_cols:
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                existing_cols.add(column_name)
        
        # Add missing columns
        for key in metadata.keys():
            safe_key = safe_metadata_key(key)
            if safe_key and safe_key not in existing_cols:
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {safe_key} TEXT")
                existing_cols.add(safe_key)
    conn.commit()

def sanitize(val):
    if val is None: return None
    if isinstance(val, str):
        return val.replace('\x00', '')
    return val

def normalize_message_id(value: Optional[str]) -> Optional[str]:
    message_id = sanitize(value)
    if not message_id:
        return None
    message_id = message_id.strip()
    if message_id.startswith("<") and message_id.endswith(">") and len(message_id) > 2:
        message_id = message_id[1:-1].strip()
    return message_id or None

def resolve_embedding_source(content: Optional[str], embedding_text: Optional[str]) -> Optional[str]:
    if embedding_text is not None:
        return sanitize(embedding_text)
    if content is not None:
        return sanitize(content)
    return None


def email_identity(metadata: Dict[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    account = sanitize(metadata.get("account")) if metadata else None
    folder = sanitize(metadata.get("folder")) if metadata else None
    uid = sanitize(metadata.get("uid")) if metadata else None
    return account, folder, uid

def email_message_id(metadata: Dict[str, Any]) -> Optional[str]:
    if not metadata:
        return None
    return normalize_message_id(metadata.get("message_id"))

@app.post("/remember")
def remember(data: MemoryCreate, token: str = Depends(verify_token)):
    try:
        clean_content = sanitize(data.content)
        embedding_source = resolve_embedding_source(data.content, data.embedding_text)
        if not embedding_source:
            raise Exception("No embedding source provided.")
        embedding_source_override = sanitize(data.embedding_text) if data.embedding_text is not None else None
        if embedding_source_override == clean_content:
            embedding_source_override = None
        now_str = str(time.time())
        metadata = data.metadata or {}
        if data.related_to:
            metadata["related_to"] = json.dumps(data.related_to)
        with get_db_connection() as conn:
            _ensure_table(conn, data.category, metadata)
            table_name = table_for(data.category)

            if data.category == "emails":
                account, folder, uid = email_identity(metadata)
                message_id = email_message_id(metadata)
                if account and message_id:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT id
                            FROM {table_name}
                            WHERE account = %s AND message_id = %s
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (account, message_id),
                        )
                        existing = cur.fetchone()
                        if existing:
                            conn.commit()
                            return {
                                "success": True,
                                "memory": {
                                    "id": existing["id"],
                                    "document": data.content,
                                    "metadata": metadata,
                                    "deduplicated": True,
                                },
                            }
                if account and folder and uid:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT id
                            FROM {table_name}
                            WHERE account = %s AND folder = %s AND uid = %s
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (account, folder, uid),
                        )
                        existing = cur.fetchone()
                        if existing:
                            conn.commit()
                            return {
                                "success": True,
                                "memory": {
                                    "id": existing["id"],
                                    "document": data.content,
                                    "metadata": metadata,
                                    "deduplicated": True,
                                },
                            }
            
            cols = [
                "document",
                "embedding",
                "embedding_source_text",
                "created_at",
                "updated_at",
                "embedding_status",
                "embedding_queued_at",
                "embedding_started_at",
                "embedding_finished_at",
                "embedding_available_at",
                "embedding_attempts",
                "embedding_error",
            ]
            vals = [
                clean_content,
                None,
                embedding_source_override,
                now_str,
                now_str,
                "pending",
                now_str,
                None,
                None,
                now_str,
                0,
                None,
            ]
            
            for k, v in metadata.items():
                safe_key = safe_metadata_key(k)
                if safe_key:
                    cols.append(safe_key)
                    vals.append(sanitize(str(v)))
                
            placeholders = ", ".join(["%s"] * len(vals))
            col_str = ", ".join(cols)
            
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders}) RETURNING id",
                    vals
                )
                mem_id = cur.fetchone()['id']
            conn.commit()
            
        return {"success": True, "memory": {"id": mem_id, "document": data.content, "metadata": metadata}}
    except Exception as e:
        logger.error(f"Error in /remember: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
def search(data: SearchQuery, token: str = Depends(verify_token)):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                emb = get_cached_embedding(data.query)
                if not emb:
                    raise Exception("Failed to generate embedding")

                ef_search = data.ef_search or HNSW_EF_SEARCH
                cur.execute(f"SET hnsw.ef_search = {ef_search}")
                emb_str = f"[{','.join(map(str, emb))}]"
                fetch_limit = max(1, min(int(data.limit or 10), 100)) * 2
                results = search_category(
                    cur,
                    data.category,
                    data.query,
                    emb_str,
                    fetch_limit,
                    data.metadata,
                    data.filters,
                    data.recency_decay,
                )
                results = rerank_candidates(data.query, results, max(1, min(int(data.limit or 10), 100)))
                    
        return {"success": True, "results": results}
    except Exception as e:
        logger.error(f"Error in /search: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search-multi")
def search_multi(data: MultiSearchQuery, token: str = Depends(verify_token)):
    try:
        categories = data.categories or sorted(ALLOWED_CATEGORIES)
        for category in categories:
            table_for(category)

        fetch_limit = max(1, min(int(data.limit or 10), 100)) * 2
        per_category_limit = max(fetch_limit * 3, 20)
        ef_search = data.ef_search or HNSW_EF_SEARCH
        started_at = time.time()
        emb = get_cached_embedding(data.query)
        if not emb:
            raise Exception("Failed to generate embedding")

        sep = ","
        emb_str = f"[{sep.join(map(str, emb))}]"
        combined: list[Dict[str, Any]] = []
        worker_count = min(len(categories), max(2, os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    search_category_parallel,
                    category,
                    data.query,
                    emb_str,
                    per_category_limit,
                    data.metadata,
                    data.filters,
                    data.recency_decay,
                    ef_search,
                ): category
                for category in categories
            }
            for future in as_completed(futures):
                category = futures[future]
                try:
                    combined.extend(future.result())
                except Exception as exc:
                    logger.warning("Search failed for category=%s query=%r: %s", category, data.query[:120], exc)

        combined = combine_candidates("multi", combined, fetch_limit, data.recency_decay)
        final_results = rerank_candidates(data.query, combined, max(1, min(int(data.limit or 10), 100)))

        return {
            "success": True,
            "results": final_results,
            "latency_ms": round((time.time() - started_at) * 1000, 2),
        }
    except Exception as e:
        logger.error(f"Error in /search-multi: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/queue-status")
def queue_status(token: str = Depends(verify_token)):
    try:
        totals = {"embedding_pending": 0, "enrichment_pending": 0}
        categories: dict[str, dict[str, int]] = {}
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for category in sorted(ALLOWED_CATEGORIES):
                    table_name = table_for(category)
                    cur.execute("SELECT to_regclass(%s)", (table_name,))
                    if not cur.fetchone()["to_regclass"]:
                        continue

                    existing_cols = existing_columns(cur, table_name)
                    embedding_pending = 0
                    enrichment_pending = 0

                    if "embedding" in existing_cols:
                        embedding_conditions = ["embedding IS NULL"]
                        if "embedding_status" in existing_cols:
                            embedding_conditions.append(
                                "(LOWER(embedding_status) IN ('pending', 'retry', 'processing') OR embedding_status IS NULL)"
                            )
                        cur.execute(
                            f"SELECT COUNT(*) AS count FROM {table_name} WHERE {' OR '.join(embedding_conditions)}"
                        )
                        embedding_pending = int(cur.fetchone()["count"])

                    if "needs_enrichment" in existing_cols:
                        cur.execute(
                            f"""
                            SELECT COUNT(*) AS count
                            FROM {table_name}
                            WHERE LOWER(needs_enrichment) IN ('true', '1', 'yes')
                            """
                        )
                        enrichment_pending = int(cur.fetchone()["count"])

                    categories[category] = {
                        "embedding_pending": embedding_pending,
                        "enrichment_pending": enrichment_pending,
                    }
                    totals["embedding_pending"] += embedding_pending
                    totals["enrichment_pending"] += enrichment_pending

        return {
            "success": True,
            "totals": totals,
            "categories": categories,
            "generated_at": utc_now(),
        }
    except Exception as e:
        logger.error(f"Error in /queue-status: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/memories/{category}")
def get_memories_endpoint(
    category: str,
    limit: int = 50,
    offset: int = 0,
    needs_enrichment: Optional[str] = None,
    token: str = Depends(verify_token),
):
    try:
        limit = max(1, min(int(limit), 250))
        offset = max(0, int(offset))
        with get_db_connection() as conn:
            table_name = table_for(category)
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (table_name,))
                if not cur.fetchone()['to_regclass']:
                    return {"success": True, "memories": []}
                
                where_sql = ""
                where_vals = []
                if needs_enrichment is not None:
                    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='needs_enrichment'", (table_name,))
                    if cur.fetchone():
                        where_sql = "WHERE LOWER(needs_enrichment) = LOWER(%s)"
                        where_vals = [needs_enrichment]
                
                query = f"""SELECT id, document,
                             {metadata_projection('t')}
                             FROM {table_name} t {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s"""
                cur.execute(query, where_vals + [limit, offset])
                rows = cur.fetchall()
                
                results = []
                for row in rows:
                    results.append({
                        "id": row['id'],
                        "document": row['document'],
                        "metadata": row['metadata']
                    })
        return {"success": True, "memories": results}
    except Exception as e:
        logger.error(f"Error in /memories: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update")
@app.post("/cascade-update")
def update(data: MemoryUpdate, token: str = Depends(verify_token)):
    try:
        with get_db_connection() as conn:
            table_name = table_for(data.category)
            metadata = data.metadata or {}
            if data.related_to:
                metadata["related_to"] = json.dumps(data.related_to)
            _ensure_table(conn, data.category, metadata)
            
            set_clauses = ["updated_at = %s"]
            set_vals = [str(time.time())]
            needs_embedding_refresh = False
            
            if data.content is not None:
                clean_content = sanitize(data.content)
                set_clauses.append("document = %s")
                set_vals.append(clean_content)
                needs_embedding_refresh = True

            embedding_source = resolve_embedding_source(data.content, data.embedding_text)
            if embedding_source is not None:
                needs_embedding_refresh = True
                now_str = str(time.time())
                embedding_source_override = sanitize(data.embedding_text) if data.embedding_text is not None else None
                if embedding_source_override == data.content:
                    embedding_source_override = None
                set_clauses.extend(
                    [
                        "embedding_status = %s",
                        "embedding_source_text = %s",
                        "embedding_queued_at = %s",
                        "embedding_started_at = %s",
                        "embedding_finished_at = %s",
                        "embedding_available_at = %s",
                        "embedding_attempts = %s",
                        "embedding_error = %s",
                    ]
                )
                set_vals.extend(["pending", embedding_source_override, now_str, None, None, now_str, 0, None])
                
            for k, v in metadata.items():
                safe_key = safe_metadata_key(k)
                if safe_key:
                    set_clauses.append(f"{safe_key} = %s")
                    set_vals.append(sanitize(str(v)))
                
            set_vals.append(data.id)
            set_sql = ", ".join(set_clauses)
            
            with conn.cursor() as cur:
                cur.execute(f"UPDATE {table_name} SET {set_sql} WHERE id = %s", set_vals)
            conn.commit()
            
        return {"success": True, "embedding_queued": needs_embedding_refresh}
    except Exception as e:
        logger.error(f"Error in /update: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete")
def delete_item(data: MemoryDelete, token: str = Depends(verify_token)):
    try:
        with get_db_connection() as conn:
            table_name = table_for(data.category)
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table_name} WHERE id = %s", [data.id])
            conn.commit()
        return {"success": True}
    except Exception as e:
        logger.error(f"Error in /delete: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete-email")
def delete_email(data: EmailDelete, token: str = Depends(verify_token)):
    try:
        account = sanitize(data.account)
        if not account:
            raise HTTPException(status_code=422, detail="Account is required")

        with get_db_connection() as conn:
            table_name = table_for("emails")
            with conn.cursor() as cur:
                existing_cols = existing_columns(cur, table_name)

            message_id = normalize_message_id(data.message_id)
            fallback_fields = [
                ("subject", sanitize(data.subject)),
                ("sender", sanitize(data.sender)),
                ("receiver", sanitize(data.receiver)),
                ("date", sanitize(data.date)),
            ]
            matched = [(field, value) for field, value in fallback_fields if value]

            delete_attempts: list[tuple[str, list[Any]]] = []
            if message_id and "message_id" in existing_cols:
                delete_attempts.append(("account = %s AND message_id = %s", [account, message_id]))
                if len(matched) >= 2:
                    delete_attempts.append(
                        (
                            " AND ".join(["account = %s", *[f"{field} = %s" for field, _ in matched]]),
                            [account, *[value for _, value in matched]],
                        )
                    )
            elif message_id and len(matched) >= 2:
                delete_attempts.append(
                    (
                        " AND ".join(["account = %s", *[f"{field} = %s" for field, _ in matched]]),
                        [account, *[value for _, value in matched]],
                    )
                )

            if data.folder and data.uid:
                delete_attempts.append(("account = %s AND folder = %s AND uid = %s", [account, sanitize(data.folder), sanitize(data.uid)]))

            if not delete_attempts and len(matched) >= 2:
                delete_attempts.append(
                    (
                        " AND ".join(["account = %s", *[f"{field} = %s" for field, _ in matched]]),
                        [account, *[value for _, value in matched]],
                    )
                )

            if not delete_attempts:
                raise HTTPException(status_code=422, detail="Need message_id or folder+uid or at least two fallback fields")

            with conn.cursor() as cur:
                deleted_ids: list[int] = []
                for where_sql, values in delete_attempts:
                    cur.execute(f"DELETE FROM {table_name} WHERE {where_sql} RETURNING id", values)
                    deleted_ids.extend(row["id"] for row in cur.fetchall())
            conn.commit()
        return {"success": True, "deleted_count": len(deleted_ids), "deleted_ids": deleted_ids}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /delete-email: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Memorex Direct-to-Postgres API",
        "version": "3.0.0"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3111)
