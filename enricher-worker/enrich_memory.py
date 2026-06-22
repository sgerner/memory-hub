import asyncio
from collections import Counter
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import aiohttp
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

AGENTMEMORY_URL = os.getenv("AGENTMEMORY_URL", "http://agentmemory:3111")
AGENTMEMORY_TOKEN = os.getenv("AGENTMEMORY_TOKEN")
SETTINGS_PATH = "/app/config/settings.json"
SECRETS_PATH = os.getenv("SECRETS_PATH", "/app/shared-settings/secrets.json")
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/enricher-worker.json")
WORKER_NAME = os.getenv("WORKER_NAME", "enricher-worker").strip() or "enricher-worker"
ENRICH_PROVIDER = os.getenv("ENRICH_PROVIDER", "opencode").strip().lower()
REMOTE_OLLAMA_HOST = os.getenv("REMOTE_OLLAMA_HOST", "").strip()
REMOTE_OLLAMA_MODEL = os.getenv("REMOTE_OLLAMA_MODEL", "qwen3.5:9b").strip()
REMOTE_OLLAMA_TIMEOUT_SECONDS = int(os.getenv("REMOTE_OLLAMA_TIMEOUT_SECONDS", "180"))
REMOTE_OLLAMA_TEXT_LIMIT = int(os.getenv("REMOTE_OLLAMA_TEXT_LIMIT", "4000"))
REMOTE_OLLAMA_NUM_PREDICT = int(os.getenv("REMOTE_OLLAMA_NUM_PREDICT", "384"))
REMOTE_OLLAMA_TEMPERATURE = float(os.getenv("REMOTE_OLLAMA_TEMPERATURE", "0.1"))
REMOTE_OLLAMA_CONCURRENCY = int(os.getenv("REMOTE_OLLAMA_CONCURRENCY", "2"))
REMOTE_OLLAMA_THINK = os.getenv("REMOTE_OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}
ENRICH_CATEGORIES = [
    item.strip()
    for item in os.getenv("ENRICH_CATEGORIES", "emails,obsidian,documents,code").split(",")
    if item.strip()
]
ENRICH_EMAIL_STRATEGY = os.getenv("ENRICH_EMAIL_STRATEGY", "all").strip().lower()
ENRICH_EMAIL_MAX_CHARS = int(os.getenv("ENRICH_EMAIL_MAX_CHARS", "1500"))
ENRICH_EMAIL_REQUIRE_NO_ATTACHMENTS = os.getenv("ENRICH_EMAIL_REQUIRE_NO_ATTACHMENTS", "true").strip().lower() in {"1", "true", "yes", "on"}

OPENCODE_GO_BASE_URL = os.getenv("LLM_BASE_URL", "https://opencode.ai/zen/go/v1")
OPENCODE_ZEN_BASE_URL = os.getenv("LLM_FREE_BASE_URL", "https://opencode.ai/zen/v1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
GEMINI_REQUEST_TIMEOUT_SECONDS = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "90"))
GEMINI_CONCURRENCY = int(os.getenv("GEMINI_CONCURRENCY", "8"))
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip()
NVIDIA_REQUEST_TIMEOUT_SECONDS = int(os.getenv("NVIDIA_REQUEST_TIMEOUT_SECONDS", "90"))
NVIDIA_REQUESTS_PER_MINUTE = int(os.getenv("NVIDIA_REQUESTS_PER_MINUTE", "15"))
NVIDIA_CONCURRENCY = int(os.getenv("NVIDIA_CONCURRENCY", "2"))
NVIDIA_MAX_TOKENS = int(os.getenv("NVIDIA_MAX_TOKENS", "512"))
NVIDIA_TEMPERATURE = float(os.getenv("NVIDIA_TEMPERATURE", "0.2"))
NVIDIA_ENABLE_THINKING = os.getenv("NVIDIA_ENABLE_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}
PRIMARY_COOLDOWN_SECONDS = 5 * 60 * 60
PRIMARY_COOLDOWN_STATE_PATH = os.getenv(
    "PRIMARY_COOLDOWN_STATE_PATH",
    "/app/status/enricher-worker-primary-cooldown.json",
)
FALLBACK_COOLDOWN_SECONDS = int(os.getenv("FALLBACK_COOLDOWN_SECONDS", str(15 * 60)))
FALLBACK_COOLDOWN_STATE_PATH = os.getenv(
    "FALLBACK_COOLDOWN_STATE_PATH",
    "/app/status/enricher-worker-fallback-cooldown.json",
)

BATCH_SIZE = int(os.getenv("ENRICH_BATCH_SIZE", "100"))
SLEEP_INTERVAL = int(os.getenv("ENRICH_SLEEP_INTERVAL", "10"))
CONCURRENCY = int(os.getenv("ENRICH_CONCURRENCY", "50"))
ENRICHMENT_VERSION = "2"
CATEGORY_LABELS = {
    "emails": "email message",
    "obsidian": "Obsidian note",
    "documents": "document",
    "code": "code file",
    "agent": "agent interaction",
}
EXCLUDED_METADATA_KEYS = {
    "id",
    "document",
    "embedding",
    "created_at",
    "updated_at",
    "needs_enrichment",
    "enrichment_version",
}
SOURCE_METADATA_PRIORITY = {
    "emails": ["subject", "from", "sender", "to", "cc", "bcc", "thread", "thread_id", "message_id", "date", "timestamp", "account", "folder", "label"],
    "documents": ["title", "name", "path", "file_path", "filepath", "filename", "source", "origin", "project", "author", "tags", "folder"],
    "obsidian": ["title", "name", "path", "vault", "note", "tags", "frontmatter", "project", "source"],
    "code": ["repository", "repo", "path", "file_path", "filename", "language", "symbol", "symbols", "module", "package", "branch", "project"],
    "agent": ["memory_kind", "created_by", "session_id", "conversation_id", "repo", "topic", "importance", "plugin", "hook_event"],
}
HEURISTIC_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "your", "you", "are", "not", "but",
    "was", "were", "will", "can", "could", "should", "would", "there", "their", "about", "into", "over",
    "then", "than", "when", "what", "which", "where", "who", "why", "how", "has", "had", "been", "its",
    "our", "out", "use", "used", "using", "one", "two", "also", "any", "all", "more", "most", "some",
    "can", "may", "might", "need", "needs", "needto", "please", "thanks", "thank", "subject", "re", "fw",
    "fwd", "doc", "note", "email", "message", "file", "code", "project",
}

memory_session = requests.Session()
if AGENTMEMORY_TOKEN:
    memory_session.headers.update({"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_status(status):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    temp_path = f"{STATUS_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(status, handle)
    os.replace(temp_path, STATUS_PATH)


def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return fallback
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error("Could not load %s: %s", path, exc)
        return fallback


def load_settings():
    settings = {
        "batch_size": BATCH_SIZE,
        "sleep_interval": SLEEP_INTERVAL,
        "concurrency": CONCURRENCY,
        "gemini_concurrency": GEMINI_CONCURRENCY,
        "text_limit": 8000,
        "gemini_model": GEMINI_MODEL,
        "gemini_request_timeout_seconds": GEMINI_REQUEST_TIMEOUT_SECONDS,
        "nvidia_api_key": NVIDIA_API_KEY,
        "nvidia_base_url": NVIDIA_BASE_URL,
        "nvidia_model": NVIDIA_MODEL,
        "nvidia_request_timeout_seconds": NVIDIA_REQUEST_TIMEOUT_SECONDS,
        "nvidia_requests_per_minute": NVIDIA_REQUESTS_PER_MINUTE,
        "nvidia_concurrency": NVIDIA_CONCURRENCY,
        "nvidia_max_tokens": NVIDIA_MAX_TOKENS,
        "nvidia_temperature": NVIDIA_TEMPERATURE,
        "nvidia_enable_thinking": NVIDIA_ENABLE_THINKING,
        "remote_ollama_host": REMOTE_OLLAMA_HOST,
        "remote_ollama_model": REMOTE_OLLAMA_MODEL,
        "remote_ollama_timeout_seconds": REMOTE_OLLAMA_TIMEOUT_SECONDS,
        "remote_ollama_text_limit": REMOTE_OLLAMA_TEXT_LIMIT,
        "remote_ollama_num_predict": REMOTE_OLLAMA_NUM_PREDICT,
        "remote_ollama_temperature": REMOTE_OLLAMA_TEMPERATURE,
        "remote_ollama_concurrency": REMOTE_OLLAMA_CONCURRENCY,
        "remote_ollama_think": REMOTE_OLLAMA_THINK,
        "enrich_categories": ENRICH_CATEGORIES,
        "email_strategy": ENRICH_EMAIL_STRATEGY,
        "email_max_chars": ENRICH_EMAIL_MAX_CHARS,
        "email_require_no_attachments": ENRICH_EMAIL_REQUIRE_NO_ATTACHMENTS,
        "email_primary_provider": "opencode",
        "email_fallback_provider": "opencode",
        "email_model": "deepseek-v4-flash",
        "email_fallback_model": "deepseek-v4-flash-free",
        "knowledge_model": "deepseek-v4-flash",
        "knowledge_fallback_model": "deepseek-v4-flash-free",
        "knowledge_primary_provider": "opencode",
        "knowledge_fallback_provider": "opencode",
        "fallback_requests_per_minute": 4,
    }
    configured = load_json(SETTINGS_PATH, {})
    for key in ("batch_size", "sleep_interval", "concurrency", "gemini_concurrency", "text_limit", "fallback_requests_per_minute", "remote_ollama_timeout_seconds", "remote_ollama_text_limit", "remote_ollama_num_predict", "remote_ollama_temperature", "remote_ollama_concurrency", "email_max_chars", "nvidia_request_timeout_seconds", "nvidia_requests_per_minute", "nvidia_concurrency", "nvidia_max_tokens", "nvidia_temperature"):
        if key in configured:
            settings[key] = float(configured[key]) if key in {"remote_ollama_temperature", "nvidia_temperature"} else int(configured[key])
    for key in ("remote_ollama_host", "remote_ollama_model", "email_primary_provider", "email_model", "email_fallback_provider", "email_fallback_model", "knowledge_model", "knowledge_fallback_model", "knowledge_primary_provider", "knowledge_fallback_provider", "email_strategy", "nvidia_base_url", "nvidia_model"):
        if key in configured:
            settings[key] = str(configured[key])
    for key in ("remote_ollama_think", "email_require_no_attachments", "nvidia_enable_thinking"):
        if key in configured:
            settings[key] = normalize_bool(configured[key])
    if "enrich_categories" in configured:
        configured_categories = configured["enrich_categories"]
        if isinstance(configured_categories, str):
            settings["enrich_categories"] = [item.strip() for item in configured_categories.split(",") if item.strip()]
        elif isinstance(configured_categories, list):
            settings["enrich_categories"] = [str(item).strip() for item in configured_categories if str(item).strip()]

    env_overrides = {
        "batch_size": os.getenv("ENRICH_BATCH_SIZE"),
        "sleep_interval": os.getenv("ENRICH_SLEEP_INTERVAL"),
        "concurrency": os.getenv("ENRICH_CONCURRENCY"),
        "gemini_concurrency": os.getenv("GEMINI_CONCURRENCY"),
        "text_limit": os.getenv("ENRICH_TEXT_LIMIT"),
        "remote_ollama_host": os.getenv("REMOTE_OLLAMA_HOST"),
        "remote_ollama_model": os.getenv("REMOTE_OLLAMA_MODEL"),
        "remote_ollama_timeout_seconds": os.getenv("REMOTE_OLLAMA_TIMEOUT_SECONDS"),
        "remote_ollama_text_limit": os.getenv("REMOTE_OLLAMA_TEXT_LIMIT"),
        "remote_ollama_num_predict": os.getenv("REMOTE_OLLAMA_NUM_PREDICT"),
        "remote_ollama_temperature": os.getenv("REMOTE_OLLAMA_TEMPERATURE"),
        "remote_ollama_concurrency": os.getenv("REMOTE_OLLAMA_CONCURRENCY"),
        "remote_ollama_think": os.getenv("REMOTE_OLLAMA_THINK"),
        "enrich_categories": os.getenv("ENRICH_CATEGORIES"),
        "email_strategy": os.getenv("ENRICH_EMAIL_STRATEGY"),
        "email_max_chars": os.getenv("ENRICH_EMAIL_MAX_CHARS"),
        "email_require_no_attachments": os.getenv("ENRICH_EMAIL_REQUIRE_NO_ATTACHMENTS"),
        "fallback_requests_per_minute": os.getenv("ENRICH_FALLBACK_REQUESTS_PER_MINUTE"),
        "email_primary_provider": os.getenv("ENRICH_EMAIL_PRIMARY_PROVIDER"),
        "email_fallback_provider": os.getenv("ENRICH_EMAIL_FALLBACK_PROVIDER"),
        "email_model": os.getenv("ENRICH_EMAIL_MODEL"),
        "email_fallback_model": os.getenv("ENRICH_EMAIL_FALLBACK_MODEL"),
        "knowledge_model": os.getenv("ENRICH_KNOWLEDGE_MODEL"),
        "knowledge_fallback_model": os.getenv("ENRICH_KNOWLEDGE_FALLBACK_MODEL"),
        "knowledge_primary_provider": os.getenv("ENRICH_KNOWLEDGE_PRIMARY_PROVIDER"),
        "knowledge_fallback_provider": os.getenv("ENRICH_KNOWLEDGE_FALLBACK_PROVIDER"),
        "nvidia_base_url": os.getenv("NVIDIA_BASE_URL"),
        "nvidia_model": os.getenv("NVIDIA_MODEL"),
        "nvidia_request_timeout_seconds": os.getenv("NVIDIA_REQUEST_TIMEOUT_SECONDS"),
        "nvidia_requests_per_minute": os.getenv("NVIDIA_REQUESTS_PER_MINUTE"),
        "nvidia_concurrency": os.getenv("NVIDIA_CONCURRENCY"),
        "nvidia_max_tokens": os.getenv("NVIDIA_MAX_TOKENS"),
        "nvidia_temperature": os.getenv("NVIDIA_TEMPERATURE"),
        "nvidia_enable_thinking": os.getenv("NVIDIA_ENABLE_THINKING"),
    }
    for key, value in env_overrides.items():
        if value is None or value == "":
            continue
        if key in {"remote_ollama_think", "email_require_no_attachments", "nvidia_enable_thinking"}:
            settings[key] = normalize_bool(value)
            continue
        if key in {"remote_ollama_host", "remote_ollama_model", "email_primary_provider", "email_fallback_provider", "email_model", "email_fallback_model", "knowledge_model", "knowledge_fallback_model", "knowledge_primary_provider", "knowledge_fallback_provider", "email_strategy", "nvidia_base_url", "nvidia_model"}:
            settings[key] = str(value)
        elif key in {"remote_ollama_temperature", "nvidia_temperature"}:
            settings[key] = float(value)
        elif key == "enrich_categories":
            settings[key] = [item.strip() for item in str(value).split(",") if item.strip()]
        else:
            settings[key] = int(value)
    return settings


def load_secrets():
    secrets = load_json(SECRETS_PATH, {})
    primary_api_key = str(secrets.get("llm_api_key") or os.getenv("LLM_API_KEY", "")).strip()
    return {
        "llm_api_key": primary_api_key,
        "gemini_api_key": str(secrets.get("gemini_api_key") or os.getenv("GEMINI_API_KEY", "")).strip(),
        "nvidia_api_key": str(secrets.get("nvidia_api_key") or os.getenv("NVIDIA_API_KEY", "")).strip(),
        "fallback_api_key": str(
            secrets.get("fallback_llm_api_key")
            or secrets.get("llm_fallback_api_key")
            or primary_api_key
            or os.getenv("LLM_FALLBACK_API_KEY", "")
        ).strip(),
    }


def effective_concurrency(settings, secrets):
    if ENRICH_PROVIDER == "remote_ollama":
        return max(1, settings["remote_ollama_concurrency"])
    if ENRICH_PROVIDER == "gemini":
        return max(1, settings["gemini_concurrency"])
    if secrets["llm_api_key"]:
        return settings["concurrency"]
    fallback_capacity = max(1, settings["fallback_requests_per_minute"] // 2)
    return max(1, min(settings["concurrency"], fallback_capacity))


def parse_timestamp(value) -> float:
    text = normalize_text(value)
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def iso_from_epoch(epoch_seconds: float) -> str:
    if epoch_seconds <= 0:
        return ""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


class PrimaryCooldownState:
    def __init__(self, path: str = PRIMARY_COOLDOWN_STATE_PATH, duration_seconds: int = PRIMARY_COOLDOWN_SECONDS):
        self.path = path
        self.duration_seconds = duration_seconds
        self.cooldown_until = self._load()

    def _load(self) -> float:
        state = load_json(self.path, {})
        cooldown_until = parse_timestamp(state.get("primary_rate_limited_until"))
        if cooldown_until <= time.time():
            return 0.0
        return cooldown_until

    def is_active(self) -> bool:
        return self.cooldown_until > time.time()

    def remaining_seconds(self) -> int:
        if not self.is_active():
            return 0
        return max(0, int(self.cooldown_until - time.time()))

    def until_iso(self) -> str:
        return iso_from_epoch(self.cooldown_until)

    def activate(self, primary_model: str) -> None:
        self.cooldown_until = time.time() + self.duration_seconds
        payload = {
            "primary_rate_limited_until": self.until_iso(),
            "primary_rate_limited_for_seconds": self.duration_seconds,
            "primary_rate_limited_model": primary_model,
            "updated_at": utc_now(),
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, self.path)


class FallbackCooldownState:
    def __init__(self, path: str = FALLBACK_COOLDOWN_STATE_PATH, duration_seconds: int = FALLBACK_COOLDOWN_SECONDS):
        self.path = path
        self.duration_seconds = duration_seconds
        self.cooldown_until = self._load()

    def _load(self) -> float:
        state = load_json(self.path, {})
        cooldown_until = parse_timestamp(state.get("fallback_rate_limited_until"))
        if cooldown_until <= time.time():
            return 0.0
        return cooldown_until

    def is_active(self) -> bool:
        return self.cooldown_until > time.time()

    def remaining_seconds(self) -> int:
        if not self.is_active():
            return 0
        return max(0, int(self.cooldown_until - time.time()))

    def until_iso(self) -> str:
        return iso_from_epoch(self.cooldown_until)

    def activate(self, fallback_model: str) -> None:
        self.cooldown_until = time.time() + self.duration_seconds
        payload = {
            "fallback_rate_limited_until": self.until_iso(),
            "fallback_rate_limited_for_seconds": self.duration_seconds,
            "fallback_rate_limited_model": fallback_model,
            "updated_at": utc_now(),
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, self.path)


def provider_status_fields(
    settings,
    secrets,
    primary_cooldown: PrimaryCooldownState,
    fallback_cooldown: FallbackCooldownState | None = None,
) -> dict:
    remote_email_active = ENRICH_PROVIDER == "remote_ollama" and bool(settings.get("remote_ollama_host")) and bool(settings.get("remote_ollama_model"))
    remote_email_fields = {
        "remote_email_provider": f"ollama:{settings['remote_ollama_model']}" if remote_email_active else "none",
        "remote_email_enabled": remote_email_active,
        "remote_email_max_chars": settings.get("email_max_chars", ENRICH_EMAIL_MAX_CHARS),
        "remote_email_concurrency": settings.get("remote_ollama_concurrency", REMOTE_OLLAMA_CONCURRENCY),
        "email_strategy": settings.get("email_strategy", ENRICH_EMAIL_STRATEGY),
        "enrich_categories": settings.get("enrich_categories", ENRICH_CATEGORIES),
    }
    email_primary_provider = resolve_provider_name(settings.get("email_primary_provider", "auto"), settings.get("email_model", ""))
    email_fallback_provider = resolve_provider_name(settings.get("email_fallback_provider", "auto"), settings.get("email_fallback_model", ""))
    if ENRICH_PROVIDER == "remote_ollama":
        return {
            "primary_provider": f"ollama:{settings['remote_ollama_model']}" if remote_email_active else "none",
            "fallback_provider": "none",
            "primary_cooldown_active": False,
            "primary_cooldown_until": "",
            "primary_cooldown_remaining_seconds": 0,
            "fallback_cooldown_active": False,
            "fallback_cooldown_until": "",
            "fallback_cooldown_remaining_seconds": 0,
            **remote_email_fields,
        }
    if ENRICH_PROVIDER == "gemini":
        gemini_active = bool(secrets["gemini_api_key"])
        return {
            "primary_provider": f"gemini:{settings['gemini_model']}" if gemini_active else "none",
            "fallback_provider": "none",
            "primary_cooldown_active": False,
            "primary_cooldown_until": "",
            "primary_cooldown_remaining_seconds": 0,
            "fallback_cooldown_active": False,
            "fallback_cooldown_until": "",
            "fallback_cooldown_remaining_seconds": 0,
            **remote_email_fields,
        }

    primary_active = bool(secrets["llm_api_key"])
    fallback_active = bool(secrets["fallback_api_key"])
    knowledge_primary_provider = resolve_provider_name(settings.get("knowledge_primary_provider", "auto"), settings.get("knowledge_model", ""))
    knowledge_fallback_provider = resolve_provider_name(settings.get("knowledge_fallback_provider", "auto"), settings.get("knowledge_fallback_model", ""))
    return {
        "primary_provider": f"opencode-go:{settings['knowledge_model']}" if primary_active else "none",
        "fallback_provider": f"opencode-zen:{settings['knowledge_fallback_model']}" if fallback_active else "none",
        "email_primary_provider": f"{email_primary_provider}:{settings['email_model']}" if email_primary_provider != "none" else "none",
        "email_fallback_provider": f"{email_fallback_provider}:{settings['email_fallback_model']}" if email_fallback_provider != "none" else "none",
        "knowledge_primary_provider": f"{knowledge_primary_provider}:{settings['knowledge_model']}" if knowledge_primary_provider != "none" else "none",
        "knowledge_fallback_provider": f"{knowledge_fallback_provider}:{settings['knowledge_fallback_model']}" if knowledge_fallback_provider != "none" else "none",
        "nvidia_primary_provider": f"nvidia-nim:{settings['nvidia_model']}" if bool(secrets["nvidia_api_key"]) else "none",
        "nvidia_enabled": bool(secrets["nvidia_api_key"]),
        "nvidia_model": settings.get("nvidia_model", NVIDIA_MODEL),
        "nvidia_base_url": settings.get("nvidia_base_url", NVIDIA_BASE_URL),
        "nvidia_requests_per_minute": settings.get("nvidia_requests_per_minute", NVIDIA_REQUESTS_PER_MINUTE),
        "nvidia_enable_thinking": settings.get("nvidia_enable_thinking", NVIDIA_ENABLE_THINKING),
        "primary_cooldown_active": primary_cooldown.is_active(),
        "primary_cooldown_until": primary_cooldown.until_iso(),
        "primary_cooldown_remaining_seconds": primary_cooldown.remaining_seconds(),
        "fallback_cooldown_active": fallback_cooldown.is_active() if fallback_cooldown else False,
        "fallback_cooldown_until": fallback_cooldown.until_iso() if fallback_cooldown else "",
        "fallback_cooldown_remaining_seconds": fallback_cooldown.remaining_seconds() if fallback_cooldown else 0,
        **remote_email_fields,
    }


def refresh_status_with_cooldown(
    settings,
    secrets,
    primary_cooldown: PrimaryCooldownState,
    fallback_cooldown: FallbackCooldownState | None = None,
) -> None:
    try:
        status = load_json(STATUS_PATH, {})
        if not isinstance(status, dict):
            status = {}
        status.update(provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown))
        status["updated_at"] = utc_now()
        save_status(status)
    except Exception as exc:
        logger.error("Failed to refresh status after primary cooldown: %s", exc)


def normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    return str(value).replace("\x00", "").strip()


def resolve_provider_name(provider_name: str, model_name: str) -> str:
    provider = normalize_text(provider_name).lower()
    if provider in {"", "auto"}:
        model = normalize_text(model_name).lower()
        if model.startswith("nvidia/"):
            return "nvidia_nim"
        return "opencode"
    if provider in {"none", "off"}:
        return "none"
    return provider


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return normalize_text(value).lower() in {"1", "true", "yes", "y", "on"}


def normalize_list(value, max_items: int = 8):
    if isinstance(value, list):
        items = [normalize_text(item) for item in value]
    elif isinstance(value, str):
        text = normalize_text(value)
        if not text:
            items = []
        else:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                items = [normalize_text(item) for item in parsed]
            else:
                items = [part.strip() for part in re.split(r"[,\n;]+", text) if part.strip()]
    else:
        items = []

    seen = set()
    result = []
    for item in items:
        lowered = item.lower()
        if not item or lowered in seen:
            continue
        seen.add(lowered)
        result.append(item)
        if len(result) >= max_items:
            break
    return result


def display_name(key: str) -> str:
    return key.replace("_", " ").strip().title()


def normalize_metadata_value(value, max_length: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        text = "; ".join(normalize_list(value, max_items=12))
    elif isinstance(value, dict):
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except Exception:
            text = normalize_text(value)
    else:
        text = normalize_text(value)
    return text[:max_length]


def split_sentences(text: str, max_sentences: int = 2, max_chars: int = 400) -> str:
    clean = normalize_text(text)
    if not clean:
        return ""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
    summary = " ".join(sentences[:max_sentences]).strip()
    if not summary:
        summary = clean[:max_chars].strip()
    return summary[:max_chars].strip()


def pick_metadata_value(metadata: dict, keys: list[str]) -> str:
    for key in keys:
        value = normalize_text(metadata.get(key))
        if value:
            return value
    return ""


def basename_without_extension(path: str) -> str:
    base = os.path.basename(normalize_text(path))
    if not base:
        return ""
    return os.path.splitext(base)[0]


def extract_keywords(text: str, limit: int = 6) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9#+_.-]{2,}", normalize_text(text).lower())
    counts = Counter(token for token in tokens if token not in HEURISTIC_STOPWORDS and not token.isdigit())
    return [word for word, _ in counts.most_common(limit)]


def extract_email_addresses(text: str) -> list[str]:
    return normalize_list(re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", normalize_text(text)), max_items=12)


def parse_category_selection(value) -> list[str]:
    if isinstance(value, list):
        return [normalize_text(item) for item in value if normalize_text(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return ["emails", "obsidian", "documents", "code"]


def email_matches_strategy(text: str, source_metadata: dict, settings: dict) -> bool:
    strategy = normalize_text(settings.get("email_strategy", ENRICH_EMAIL_STRATEGY)).lower()
    max_chars = int(settings.get("email_max_chars", ENRICH_EMAIL_MAX_CHARS))
    require_no_attachments = bool(settings.get("email_require_no_attachments", ENRICH_EMAIL_REQUIRE_NO_ATTACHMENTS))
    body = normalize_text(strip_existing_enrichment(text))
    if not body:
        return False
    has_attachments = "attachments:" in body.lower() or "attachment content:" in body.lower()
    small_email = len(body) <= max_chars and (not require_no_attachments or not has_attachments)
    if strategy in {"all", ""}:
        return True
    if strategy == "small_only":
        return small_email
    if strategy == "large_only":
        return not small_email
    if strategy == "no_attachments":
        return not has_attachments
    if strategy == "off":
        return False
    return True


def extract_dates(text: str, metadata: dict) -> list[str]:
    dates = []
    for key in ("date", "datetime", "sent_at", "received_at", "created_at", "updated_at", "timestamp"):
        value = normalize_text(metadata.get(key))
        if value:
            dates.append(value)
    dates.extend(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", normalize_text(text)))
    dates.extend(re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", normalize_text(text)))
    return normalize_list(dates, max_items=8)


def extract_action_items(text: str) -> list[str]:
    items = []
    for line in normalize_text(text).splitlines():
        lowered = line.lower()
        if any(phrase in lowered for phrase in ("todo", "follow up", "please", "need to", "needs to", "action item", "can you", "should", "must")):
            cleaned = line.strip(" -*•\t")
            if cleaned:
                items.append(cleaned)
        if len(items) >= 5:
            break
    if not items and "?" in text:
        items.append("Review open questions")
    return normalize_list(items, max_items=5)


def extract_question_lines(text: str) -> list[str]:
    lines = []
    for line in normalize_text(text).splitlines():
        cleaned = line.strip(" -*•\t")
        if cleaned.endswith("?") or cleaned.lower().startswith(("why ", "what ", "how ", "when ", "where ", "who ")):
            lines.append(cleaned)
        if len(lines) >= 4:
            break
    return normalize_list(lines, max_items=4)


def guess_language_from_path(metadata: dict) -> str:
    path = pick_metadata_value(metadata, ["path", "file_path", "filename", "name"])
    if not path:
        return ""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".jsx": "JavaScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".rb": "Ruby",
        ".sh": "Shell",
        ".md": "Markdown",
        ".json": "JSON",
        ".yaml": "YAML",
        ".yml": "YAML",
    }.get(ext, "")


def extract_symbols(text: str) -> list[str]:
    patterns = [
        r"(?m)^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?m)^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?m)^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?m)^\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?m)^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]
    symbols = []
    source = normalize_text(text)
    for pattern in patterns:
        symbols.extend(re.findall(pattern, source))
        if len(symbols) >= 12:
            break
    return normalize_list(symbols, max_items=12)


def extract_dependencies(text: str) -> list[str]:
    source = normalize_text(text)
    deps = []
    deps.extend(re.findall(r"(?m)^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", source))
    deps.extend(re.findall(r"(?m)^\s*from\s+([A-Za-z0-9_.\-\/]+)\s+import\s+", source))
    deps.extend(re.findall(r"require\(['\"]([^'\"]+)['\"]\)", source))
    return normalize_list(deps, max_items=10)


def heuristic_enrichment(category: str, text: str, source_metadata: dict) -> dict:
    source_context = build_source_context(category, source_metadata, limit=12)
    combined_context = "\n".join(part for part in [normalize_text(text), source_context] if part)

    title = pick_metadata_value(source_metadata, ["subject", "title", "name", "filename"])
    if not title:
        title = basename_without_extension(pick_metadata_value(source_metadata, ["path", "file_path", "filename", "name"]))
    if not title and category == "agent":
        title = pick_metadata_value(source_metadata, ["memory_kind", "kind", "repo", "topic"]) or split_sentences(text, max_sentences=1, max_chars=120)
    summary = split_sentences(text, max_sentences=2, max_chars=500) or title
    topic_seed = " ".join(part for part in [title, summary, source_context, normalize_text(text)[:4000]] if part)
    topics = normalize_list(extract_keywords(topic_seed, limit=8) + normalize_list(source_metadata.get("tags"), max_items=8), max_items=8)
    people = normalize_list(
        [
            *normalize_list(source_metadata.get("people"), max_items=8),
            *normalize_list(source_metadata.get("sender"), max_items=4),
            *normalize_list(source_metadata.get("from"), max_items=4),
            *normalize_list(source_metadata.get("to"), max_items=8),
            *normalize_list(source_metadata.get("cc"), max_items=8),
            *normalize_list(source_metadata.get("bcc"), max_items=8),
            *extract_email_addresses(combined_context),
        ],
        max_items=12,
    )
    organizations = normalize_list(
        [
            *normalize_list(source_metadata.get("organizations"), max_items=8),
            *normalize_list(source_metadata.get("organization"), max_items=4),
            *normalize_list(source_metadata.get("company"), max_items=4),
            *normalize_list(source_metadata.get("repo"), max_items=4),
            *normalize_list(source_metadata.get("repository"), max_items=4),
        ],
        max_items=8,
    )
    dates = extract_dates(text, source_metadata)
    action_items = extract_action_items(text)
    importance = ""
    lowered = normalize_text(text).lower()
    if any(term in lowered for term in ("urgent", "asap", "critical", "blocking", "immediately")):
        importance = "high"
    elif action_items or "?" in text:
        importance = "medium"

    sender = pick_metadata_value(source_metadata, ["sender", "from", "author"])
    recipients = normalize_list(
        [
            *normalize_list(source_metadata.get("to"), max_items=8),
            *normalize_list(source_metadata.get("cc"), max_items=8),
            *normalize_list(source_metadata.get("bcc"), max_items=8),
        ],
        max_items=12,
    )
    reply_needed = category == "emails" and (bool(action_items) or "?" in text or any(term in lowered for term in ("please reply", "please respond", "let me know", "can you")))
    thread_focus = title or summary
    project = pick_metadata_value(source_metadata, ["project", "repo", "repository", "folder"])
    key_claims = extract_question_lines(text)[:3]
    open_questions = extract_question_lines(text)
    language = pick_metadata_value(source_metadata, ["language"]) or guess_language_from_path(source_metadata)
    symbols = normalize_list(source_metadata.get("symbols"), max_items=8) or extract_symbols(text)
    purpose = split_sentences(text, max_sentences=1, max_chars=250)
    dependencies = normalize_list(source_metadata.get("dependencies"), max_items=8) or extract_dependencies(text)

    if category == "code" and not project:
        project = pick_metadata_value(source_metadata, ["repository", "repo", "package", "module"])
    if category == "agent" and not project:
        project = pick_metadata_value(source_metadata, ["repo", "conversation_id", "plugin", "topic"])
    if category in {"documents", "obsidian"} and not key_claims:
        key_claims = extract_keywords(topic_seed, limit=3)
    if category == "agent" and not key_claims:
        key_claims = extract_keywords(topic_seed, limit=3)

    return {
        "title": title or summary[:120],
        "summary": summary,
        "topics": topics,
        "people": people,
        "organizations": organizations,
        "dates": dates,
        "action_items": action_items,
        "importance": importance,
        "sender": sender,
        "recipients": recipients,
        "reply_needed": reply_needed,
        "thread_focus": thread_focus,
        "project": project,
        "key_claims": key_claims,
        "open_questions": open_questions,
        "language": language,
        "symbols": symbols,
        "purpose": purpose,
        "dependencies": dependencies,
    }


def build_source_context(category: str, metadata: dict, limit: int = 8) -> str:
    if not metadata:
        return ""

    priority = SOURCE_METADATA_PRIORITY.get(category, [])
    ordered_keys = []
    for key in priority:
        if key in metadata and key not in ordered_keys:
            ordered_keys.append(key)

    for key in sorted(metadata.keys()):
        if key in ordered_keys or key in EXCLUDED_METADATA_KEYS or key.startswith("enrichment_"):
            continue
        ordered_keys.append(key)

    lines = []
    for key in ordered_keys:
        if len(lines) >= limit:
            break
        text = normalize_metadata_value(metadata.get(key))
        if text:
            lines.append(f"{display_name(key)}: {text}")
    return "\n".join(lines)


def strip_existing_enrichment(content: str) -> str:
    text = normalize_text(content)
    if not text:
        return ""

    if text.startswith("Enrichment:"):
        parts = text.split("\n\n", 1)
        if len(parts) == 2:
            return parts[1].strip()
        return ""

    summary_index = text.find("Summary:")
    if 0 <= summary_index < 2000:
        separator_index = text.find("\n\n", summary_index)
        if separator_index != -1:
            prefix = text[:summary_index]
            if "\n" in prefix or "Body:" in prefix or "Subject:" in prefix:
                return text[separator_index + 2 :].strip()

    return text


def build_structured_block(category: str, enrichment: dict, source_context: str = "") -> str:
    lines = ["Enrichment:", f"Category: {CATEGORY_LABELS.get(category, category)}"]
    if source_context:
        lines.append("Source context:")
        lines.extend([f"- {line}" for line in source_context.splitlines() if line.strip()])

    field_order = [
        ("title", "Title"),
        ("summary", "Summary"),
        ("topics", "Topics"),
        ("people", "People"),
        ("organizations", "Organizations"),
        ("dates", "Dates"),
        ("action_items", "Action items"),
        ("importance", "Importance"),
        ("sender", "Sender"),
        ("recipients", "Recipients"),
        ("reply_needed", "Reply needed"),
        ("thread_focus", "Thread focus"),
        ("project", "Project"),
        ("key_claims", "Key claims"),
        ("open_questions", "Open questions"),
        ("language", "Language"),
        ("symbols", "Symbols"),
        ("purpose", "Purpose"),
        ("dependencies", "Dependencies"),
    ]

    for key, label in field_order:
        value = enrichment.get(key)
        if isinstance(value, list):
            value_text = "; ".join(normalize_list(value, max_items=12))
        elif isinstance(value, bool):
            value_text = "yes" if value else "no"
        else:
            value_text = normalize_text(value)
        if value_text:
            lines.append(f"{label}: {value_text}")

    lines.append("")
    return "\n".join(lines) + "\n"


def build_enriched_content(category: str, original_content: str, enrichment: dict, source_context: str = "") -> str:
    body = strip_existing_enrichment(original_content)
    structured = build_structured_block(category, enrichment, source_context)
    if body:
        return f"{structured}{body}".strip()
    return structured.strip()


def build_embedding_text(category: str, original_content: str, enrichment: dict, source_context: str = "") -> str:
    body = strip_existing_enrichment(original_content)
    body_excerpt = normalize_text(body)[:6000]
    structured = build_structured_block(category, enrichment, source_context).strip()
    parts = [structured]
    if body_excerpt:
        parts.append("Body excerpt:")
        parts.append(body_excerpt)
    return "\n\n".join(part for part in parts if part).strip()


def flatten_metadata(category: str, enrichment: dict) -> dict:
    metadata = {
        "needs_enrichment": "False",
        "enrichment_version": ENRICHMENT_VERSION,
        "enrichment_source_type": CATEGORY_LABELS.get(category, category),
    }
    for key, value in enrichment.items():
        meta_key = f"enrichment_{key}"
        if isinstance(value, list):
            metadata[meta_key] = "; ".join(normalize_list(value, max_items=12))
        elif isinstance(value, bool):
            metadata[meta_key] = "true" if value else "false"
        else:
            text = normalize_text(value)
            if text:
                metadata[meta_key] = text
    return metadata


def extract_json_object(raw_text: str):
    text = normalize_text(raw_text)
    if not text:
        return None

    if text.startswith("```"):
        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def normalize_enrichment(raw_text: str, category: str):
    parsed = extract_json_object(raw_text)
    if parsed is None:
        return {
            "title": "",
            "summary": normalize_text(raw_text),
            "topics": [],
            "people": [],
            "organizations": [],
            "dates": [],
            "action_items": [],
            "importance": "",
            "sender": "",
            "recipients": [],
            "reply_needed": False,
            "thread_focus": "",
            "project": "",
            "key_claims": [],
            "open_questions": [],
            "language": "",
            "symbols": [],
            "purpose": "",
            "dependencies": [],
        }

    structured = {
        "title": normalize_text(parsed.get("title")),
        "summary": normalize_text(parsed.get("summary")),
        "topics": normalize_list(parsed.get("topics")),
        "people": normalize_list(parsed.get("people")),
        "organizations": normalize_list(parsed.get("organizations")),
        "dates": normalize_list(parsed.get("dates")),
        "action_items": normalize_list(parsed.get("action_items")),
        "importance": normalize_text(parsed.get("importance")).lower(),
        "sender": normalize_text(parsed.get("sender")),
        "recipients": normalize_list(parsed.get("recipients")),
        "reply_needed": normalize_bool(parsed.get("reply_needed")),
        "thread_focus": normalize_text(parsed.get("thread_focus")),
        "project": normalize_text(parsed.get("project")),
        "key_claims": normalize_list(parsed.get("key_claims")),
        "open_questions": normalize_list(parsed.get("open_questions")),
        "language": normalize_text(parsed.get("language")),
        "symbols": normalize_list(parsed.get("symbols")),
        "purpose": normalize_text(parsed.get("purpose")),
        "dependencies": normalize_list(parsed.get("dependencies")),
    }

    if not structured["summary"]:
        structured["summary"] = normalize_text(raw_text)
    if not structured["title"] and structured["summary"]:
        structured["title"] = structured["summary"].split(". ")[0][:120].strip()
    if structured["importance"] not in {"low", "medium", "high"}:
        structured["importance"] = ""

    # Use the category to bias a few obvious fields when the model omitted them.
    if category == "emails" and not structured["thread_focus"] and structured["title"]:
        structured["thread_focus"] = structured["title"]
    if category == "code" and not structured["project"] and structured["title"]:
        structured["project"] = structured["title"]

    return structured


def build_system_prompt(category):
    label = CATEGORY_LABELS.get(category, "record")
    return f"""You enrich a {label} for a personal memory hub.

Return ONLY valid JSON. No markdown fences. No explanation text.

Prefer compact, retrieval-friendly fields. Keep the summary to 2-3 sentences.
If a field is unknown, use an empty string, empty array, or false.
Use the source metadata when it helps identify titles, projects, people, paths, repositories, senders, recipients, or due dates.
Prefer canonical names and semantic labels over raw wording.

JSON keys:
  title: short canonical title or subject
  summary: concise semantic summary
  topics: array of short topic phrases
  people: array of people names
  organizations: array of organization names
  dates: array of date strings
  action_items: array of concrete follow-ups or commitments
  importance: low, medium, or high

Category-specific keys:
  emails: sender, recipients, reply_needed, thread_focus
  documents and obsidian notes: project, key_claims, open_questions
  code: language, symbols, project, purpose, dependencies
  agent interactions: project, language, symbols, purpose, key_claims, dependencies
"""


def build_remote_email_system_prompt():
    return """You enrich an email message for a personal memory hub.

Return ONLY valid JSON. No markdown fences. No explanation text.

Prefer compact, retrieval-friendly fields. Keep the summary to 2-3 sentences.
If a field is unknown, use an empty string, empty array, or false.
Prefer canonical names and semantic labels over raw wording.
Use the source metadata when it helps identify titles, people, senders, recipients, and due dates.

JSON keys:
  title
  summary
  topics
  people
  organizations
  dates
  action_items
  importance
  sender
  recipients
  reply_needed
  thread_focus
"""


def build_remote_email_source_context(metadata: dict, limit: int = 6) -> str:
    if not metadata:
        return ""

    ordered_keys = []
    for key in ["subject", "from", "sender", "to", "cc", "bcc", "date", "account", "folder"]:
        if key in metadata and key not in ordered_keys:
            ordered_keys.append(key)

    for key in sorted(metadata.keys()):
        if key in ordered_keys or key in EXCLUDED_METADATA_KEYS or key.startswith("enrichment_"):
            continue
        ordered_keys.append(key)

    lines = []
    for key in ordered_keys:
        if len(lines) >= limit:
            break
        text = normalize_metadata_value(metadata.get(key))
        if text:
            lines.append(f"{display_name(key)}: {text}")
    return "\n".join(lines)


def build_remote_email_user_prompt(text, text_limit, source_context=""):
    prompt = ["Category: email message"]
    if source_context:
        prompt.append(f"Source metadata:\n{source_context}")
    prompt.append(f"Source text:\n{normalize_text(text)[:text_limit]}")
    return "\n\n".join(prompt)


def build_user_prompt(category, text, text_limit, source_context=""):
    label = CATEGORY_LABELS.get(category, category)
    prompt = [f"Category: {label}"]
    if source_context:
        prompt.append(f"Source metadata:\n{source_context}")
    prompt.append(f"Source text:\n{normalize_text(text)[:text_limit]}")
    return "\n\n".join(prompt)


class RateLimiter:
    def __init__(self, requests_per_minute: int):
        self.min_interval = 60.0 / max(1, requests_per_minute)
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self):
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.time()
            wait = self.min_interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.time()


def should_use_remote_email_ollama(category: str, text: str, source_metadata: dict, settings: dict) -> bool:
    if category != "emails":
        return False

    if ENRICH_PROVIDER != "remote_ollama":
        return False
    host = normalize_text(settings.get("remote_ollama_host"))
    model = normalize_text(settings.get("remote_ollama_model"))
    if not host or not model:
        return False
    return email_matches_strategy(text, source_metadata, settings)


def get_pending_memories(settings):
    try:
        pending = []
        categories = parse_category_selection(settings.get("enrich_categories", ENRICH_CATEGORIES))
        batch_target = max(1, int(settings["batch_size"]))
        page_size = max(1, min(250, batch_target))
        for category in categories:
            category_pending = []
            offset = 0
            # Keep paging until we either fill the batch with matching rows or exhaust the category.
            while len(category_pending) < batch_target:
                url = (
                    f"{AGENTMEMORY_URL}/memories/{category}"
                    f"?limit={page_size}&offset={offset}&needs_enrichment=true"
                )
                response = memory_session.get(url, timeout=15)
                if response.status_code != 200:
                    break
                memories = response.json().get("memories", [])
                if not memories:
                    break
                for item in memories:
                    content = item.get("document", item.get("content", ""))
                    metadata = item.get("metadata") or {}
                    if category == "emails" and not email_matches_strategy(content, metadata, settings):
                        continue
                    category_pending.append(
                        {
                            "id": item.get("id"),
                            "category": category,
                            "content": content,
                            "metadata": metadata,
                        }
                    )
                    if len(category_pending) >= batch_target:
                        break
                if len(memories) < page_size:
                    break
                offset += page_size
            pending.extend(category_pending)
        return pending
    except Exception as exc:
        logger.error("Failed to fetch pending memories: %s", exc)
        return []


async def call_llm(session, api_key, base_url, model, category, text, text_limit, source_context=""):
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_system_prompt(category)},
                {"role": "user", "content": build_user_prompt(category, text, text_limit, source_context)},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        url = f"{base_url.rstrip('/')}/chat/completions"

        async with session.post(url, headers=headers, json=payload, timeout=90) as response:
            if response.status == 429:
                return "RATE_LIMIT"
            response.raise_for_status()
            data = await response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error("LLM call to %s failed: %s", model, exc)
        return None


async def call_gemini(session, api_key, model, category, text, text_limit, source_context=""):
    try:
        payload = {
            "system_instruction": {
                "parts": [{"text": build_system_prompt(category)}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": build_user_prompt(category, text, text_limit, source_context)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        async with session.post(url, json=payload, timeout=GEMINI_REQUEST_TIMEOUT_SECONDS) as response:
            if response.status == 429:
                return "RATE_LIMIT"
            response.raise_for_status()
            data = await response.json()
            candidates = data.get("candidates") or []
            for candidate in candidates:
                content = candidate.get("content") or {}
                parts = content.get("parts") or []
                texts = []
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        texts.append(part["text"])
                if texts:
                    return "\n".join(texts).strip()
            return ""
    except Exception as exc:
        logger.error("Gemini call to %s failed: %s", model, exc)
        return None


async def call_nvidia_nim(
    session,
    api_key,
    base_url,
    model,
    category,
    text,
    text_limit,
    source_context="",
    temperature: float = 0.2,
    max_tokens: int = 512,
    enable_thinking: bool = False,
    request_timeout_seconds: int = NVIDIA_REQUEST_TIMEOUT_SECONDS,
):
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_system_prompt(category)},
                {"role": "user", "content": build_user_prompt(category, text, text_limit, source_context)},
            ],
            "temperature": temperature,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {
                "enable_thinking": enable_thinking,
            },
        }
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}

        async with session.post(
            url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=request_timeout_seconds),
        ) as response:
            if response.status == 429:
                return "RATE_LIMIT"
            response.raise_for_status()
            data = await response.json()
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            return content.strip()
    except Exception as exc:
        logger.error("NVIDIA NIM call to %s failed: %s", model, exc)
        return None


async def call_ollama(session, base_url, model, text, text_limit, source_context="", temperature=0.1, num_predict=384, think=False):
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_remote_email_system_prompt()},
                {"role": "user", "content": build_remote_email_user_prompt(text, text_limit, source_context)},
            ],
            "stream": False,
            "format": "json",
            "think": think,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        url = f"{base_url.rstrip('/')}/api/chat"

        async with session.post(url, json=payload, timeout=REMOTE_OLLAMA_TIMEOUT_SECONDS) as response:
            if response.status == 429:
                return "RATE_LIMIT"
            response.raise_for_status()
            data = await response.json()
            message = data.get("message") or {}
            content = message.get("content") or ""
            return content.strip()
    except Exception as exc:
        logger.error("Ollama call to %s failed: %s", model, exc)
        return None


async def enrich_with_fallback(
    session,
    text,
    category,
    source_metadata,
    settings,
    secrets,
    limiter,
    nvidia_limiter,
    primary_cooldown,
    fallback_cooldown,
    remote_ollama_semaphore,
):
    if should_use_remote_email_ollama(category, text, source_metadata, settings):
        source_context = build_remote_email_source_context(source_metadata)
        async with remote_ollama_semaphore:
            response = await call_ollama(
                session,
                settings["remote_ollama_host"],
                settings["remote_ollama_model"],
                text,
                settings["remote_ollama_text_limit"],
                source_context,
                temperature=float(settings.get("remote_ollama_temperature", REMOTE_OLLAMA_TEMPERATURE)),
                num_predict=int(settings.get("remote_ollama_num_predict", REMOTE_OLLAMA_NUM_PREDICT)),
                think=bool(settings.get("remote_ollama_think", REMOTE_OLLAMA_THINK)),
            )
        if response == "RATE_LIMIT":
            logger.warning("Remote Ollama provider rate limited for %s.", settings["remote_ollama_model"])
            return "RATE_LIMIT"
        if response and extract_json_object(response):
            return normalize_enrichment(response, category)
        if response:
            logger.warning("Remote Ollama response for %s was not valid JSON.", settings["remote_ollama_model"])
        return None

    if ENRICH_PROVIDER == "gemini":
        if secrets["gemini_api_key"]:
            response = await call_gemini(
                session,
                secrets["gemini_api_key"],
                settings["gemini_model"],
                category,
                text,
                settings["text_limit"],
                build_source_context(category, source_metadata),
            )
            if response == "RATE_LIMIT":
                logger.warning("Gemini provider rate limited for %s.", settings["gemini_model"])
                return "RATE_LIMIT"
            if response:
                return normalize_enrichment(response, category)
        return None

    knowledge_primary_provider = resolve_provider_name(settings.get("knowledge_primary_provider", "auto"), settings.get("knowledge_model", ""))
    knowledge_fallback_provider = resolve_provider_name(settings.get("knowledge_fallback_provider", "auto"), settings.get("knowledge_fallback_model", ""))
    if category == "emails":
        email_primary_provider = resolve_provider_name(settings.get("email_primary_provider", "auto"), settings["email_model"])
        email_fallback_provider = resolve_provider_name(settings.get("email_fallback_provider", "auto"), settings["email_fallback_model"])
        primary_model = settings["email_model"]
        fallback_model = settings["email_fallback_model"]
    else:
        email_primary_provider = "opencode"
        email_fallback_provider = "opencode"
        primary_model = settings["knowledge_model"]
        fallback_model = settings["knowledge_fallback_model"]

    source_context = build_source_context(category, source_metadata)

    if category == "emails" and email_primary_provider == "nvidia_nim":
        nvidia_api_key = secrets["nvidia_api_key"]
        if nvidia_api_key:
            await nvidia_limiter.wait()
            response = await call_nvidia_nim(
                session,
                nvidia_api_key,
                settings["nvidia_base_url"],
                primary_model,
                category,
                text,
                settings["text_limit"],
                source_context,
                temperature=float(settings.get("nvidia_temperature", NVIDIA_TEMPERATURE)),
                max_tokens=int(settings.get("nvidia_max_tokens", NVIDIA_MAX_TOKENS)),
                enable_thinking=bool(settings.get("nvidia_enable_thinking", NVIDIA_ENABLE_THINKING)),
                request_timeout_seconds=int(settings.get("nvidia_request_timeout_seconds", NVIDIA_REQUEST_TIMEOUT_SECONDS)),
            )
            if response == "RATE_LIMIT":
                logger.warning("NVIDIA NIM provider rate limited for %s.", primary_model)
            elif response:
                return normalize_enrichment(response, category)
        elif email_fallback_provider == "opencode":
            logger.warning("NVIDIA API key is missing for email enrichment.")

    if category != "emails" and knowledge_primary_provider == "nvidia_nim":
        nvidia_api_key = secrets["nvidia_api_key"]
        if nvidia_api_key:
            await nvidia_limiter.wait()
            response = await call_nvidia_nim(
                session,
                nvidia_api_key,
                settings["nvidia_base_url"],
                primary_model,
                category,
                text,
                settings["text_limit"],
                source_context,
                temperature=float(settings.get("nvidia_temperature", NVIDIA_TEMPERATURE)),
                max_tokens=int(settings.get("nvidia_max_tokens", NVIDIA_MAX_TOKENS)),
                enable_thinking=bool(settings.get("nvidia_enable_thinking", NVIDIA_ENABLE_THINKING)),
                request_timeout_seconds=int(settings.get("nvidia_request_timeout_seconds", NVIDIA_REQUEST_TIMEOUT_SECONDS)),
            )
            if response == "RATE_LIMIT":
                logger.warning("NVIDIA NIM provider rate limited for %s.", primary_model)
            elif response:
                return normalize_enrichment(response, category)
        elif knowledge_fallback_provider == "opencode":
            logger.warning("NVIDIA API key is missing for %s enrichment.", category)

    if not ((category == "emails" and email_primary_provider == "nvidia_nim") or (category != "emails" and knowledge_primary_provider == "nvidia_nim")) and secrets["llm_api_key"] and not primary_cooldown.is_active():
        response = await call_llm(
            session,
            secrets["llm_api_key"],
            OPENCODE_GO_BASE_URL,
            primary_model,
            category,
            text,
            settings["text_limit"],
            source_context,
        )
        if response == "RATE_LIMIT":
            logger.warning("Primary provider rate limited for %s. Cooling off for 5 hours.", primary_model)
            primary_cooldown.activate(primary_model)
            refresh_status_with_cooldown(settings, secrets, primary_cooldown, fallback_cooldown)
        elif response:
            return normalize_enrichment(response, category)

    if fallback_cooldown.is_active():
        logger.warning("Fallback provider cooling down for %s more seconds.", fallback_cooldown.remaining_seconds())
        return "RATE_LIMIT"

    if category == "emails" and email_fallback_provider == "nvidia_nim" and secrets["nvidia_api_key"]:
        await limiter.wait()
        response = await call_nvidia_nim(
            session,
            secrets["nvidia_api_key"],
            settings["nvidia_base_url"],
            fallback_model,
            category,
            text,
            settings["text_limit"],
            source_context,
            temperature=float(settings.get("nvidia_temperature", NVIDIA_TEMPERATURE)),
            max_tokens=int(settings.get("nvidia_max_tokens", NVIDIA_MAX_TOKENS)),
            enable_thinking=bool(settings.get("nvidia_enable_thinking", NVIDIA_ENABLE_THINKING)),
            request_timeout_seconds=int(settings.get("nvidia_request_timeout_seconds", NVIDIA_REQUEST_TIMEOUT_SECONDS)),
        )
        if response == "RATE_LIMIT":
            logger.warning("Fallback provider rate limited for %s.", fallback_model)
            fallback_cooldown.activate(fallback_model)
            return "RATE_LIMIT"
        if response:
            return normalize_enrichment(response, category)

    if category == "emails" and email_fallback_provider == "none":
        return None

    if secrets["llm_api_key"]:
        await limiter.wait()
        response = await call_llm(
            session,
            secrets["llm_api_key"],
            OPENCODE_GO_BASE_URL,
            fallback_model,
            category,
            text,
            settings["text_limit"],
            source_context,
        )
        if response == "RATE_LIMIT":
            logger.warning("OpenCode GO fallback rate limited for %s.", fallback_model)
            fallback_cooldown.activate(fallback_model)
            return "RATE_LIMIT"
        if response:
            return normalize_enrichment(response, category)

    return None


async def update_memory(session, memory_id, category, original_content, enrichment, source_metadata):
    try:
        headers = {"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"}
        source_context = build_source_context(category, source_metadata)
        new_content = build_enriched_content(category, original_content, enrichment, source_context)
        payload = {
            "id": str(memory_id),
            "category": category,
            "content": new_content,
            "metadata": flatten_metadata(category, enrichment),
            "embedding_text": build_embedding_text(category, original_content, enrichment, source_context),
        }

        timeout = aiohttp.ClientTimeout(total=300)
        async with session.post(f"{AGENTMEMORY_URL}/update", headers=headers, json=payload, timeout=timeout) as response:
            if response.status not in (200, 201):
                body = await response.text()
                logger.error(
                    "AgentMemory update failed for %s (status %s): %s",
                    memory_id,
                    response.status,
                    body[:500],
                )
                return False
            return True
    except Exception as exc:
        logger.error("Failed to update memory %s: %r", memory_id, exc)
        return False


async def process_item(
    session,
    semaphore,
    item,
    settings,
    secrets,
    limiter,
    nvidia_limiter,
    primary_cooldown,
    fallback_cooldown,
    remote_ollama_semaphore,
):
    async with semaphore:
        memory_id = item["id"]
        content = item["content"]
        category = item["category"]
        source_metadata = item.get("metadata") or {}

        enrichment = await enrich_with_fallback(
            session,
            content,
            category,
            source_metadata,
            settings,
            secrets,
            limiter,
            nvidia_limiter,
            primary_cooldown,
            fallback_cooldown,
            remote_ollama_semaphore,
        )
        if enrichment == "RATE_LIMIT":
            return "RATE_LIMIT"

        if enrichment:
            success = await update_memory(session, memory_id, category, content, enrichment, source_metadata)
            if success:
                logger.info("Successfully enriched memory %s in %s", memory_id, category)
                return "SUCCESS"
            logger.error("Failed to save enrichment for %s", memory_id)
            return "FAILED"

        return "SKIPPED"


async def enrich_batch():
    settings = load_settings()
    secrets = load_secrets()
    concurrency = effective_concurrency(settings, secrets)
    pending = get_pending_memories(settings)
    fallback_requests_per_minute = max(1, settings["fallback_requests_per_minute"])
    nvidia_requests_per_minute = max(1, int(settings.get("nvidia_requests_per_minute", NVIDIA_REQUESTS_PER_MINUTE)))
    primary_cooldown = PrimaryCooldownState()
    fallback_cooldown = FallbackCooldownState()
    remote_ollama_semaphore = asyncio.Semaphore(max(1, int(settings.get("remote_ollama_concurrency", REMOTE_OLLAMA_CONCURRENCY))))

    if not pending:
        now = utc_now()
        save_status(
            {
                "service": WORKER_NAME,
                "status": "idle",
                "last_cycle_started_at": now,
                "last_cycle_finished_at": now,
                "last_success_at": now,
                "items_processed": 0,
                "items_remaining": 0,
                **provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown),
                "concurrency": concurrency,
                "batch_size": settings["batch_size"],
                "rate_limit_per_minute": fallback_requests_per_minute,
                "nvidia_rate_limit_per_minute": nvidia_requests_per_minute,
                "email_strategy": settings.get("email_strategy", ENRICH_EMAIL_STRATEGY),
                "enrich_categories": settings.get("enrich_categories", ENRICH_CATEGORIES),
                "updated_at": now,
            }
        )
        logger.info("No memories pending enrichment. Sleeping...")
        return False

    started_at = utc_now()
    limiter = RateLimiter(fallback_requests_per_minute)
    nvidia_limiter = RateLimiter(nvidia_requests_per_minute)
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency)

    save_status(
        {
            "service": WORKER_NAME,
            "status": "running",
            "last_cycle_started_at": started_at,
            "items_total": len(pending),
            "items_remaining": len(pending),
            **provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown),
            "concurrency": concurrency,
            "batch_size": settings["batch_size"],
            "rate_limit_per_minute": fallback_requests_per_minute,
            "nvidia_rate_limit_per_minute": nvidia_requests_per_minute,
            "email_strategy": settings.get("email_strategy", ENRICH_EMAIL_STRATEGY),
            "enrich_categories": settings.get("enrich_categories", ENRICH_CATEGORIES),
            "updated_at": started_at,
        }
    )

    enriched_count = 0
    skipped_count = 0

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(
                process_item(session, semaphore, item, settings, secrets, limiter, nvidia_limiter, primary_cooldown, fallback_cooldown, remote_ollama_semaphore)
            )
            for item in pending
        ]

        try:
            for completed in asyncio.as_completed(tasks):
                result = await completed
                if result == "SUCCESS":
                    enriched_count += 1
                elif result == "SKIPPED":
                    skipped_count += 1
                elif result == "RATE_LIMIT":
                    logger.warning("Fallback provider saturated. Ending batch early.")
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    finished_at = utc_now()
                    save_status(
                        {
                            "service": WORKER_NAME,
                            "status": "deferred",
                            "last_cycle_started_at": started_at,
                            "last_cycle_finished_at": finished_at,
                            "items_processed": enriched_count,
                            "items_remaining": max(0, len(pending) - enriched_count - skipped_count),
                            **provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown),
                            "concurrency": concurrency,
                            "batch_size": settings["batch_size"],
                            "rate_limit_per_minute": fallback_requests_per_minute,
                            "nvidia_rate_limit_per_minute": nvidia_requests_per_minute,
                            "email_strategy": settings.get("email_strategy", ENRICH_EMAIL_STRATEGY),
                            "enrich_categories": settings.get("enrich_categories", ENRICH_CATEGORIES),
                            "updated_at": finished_at,
                        }
                    )
                    return False
        except Exception as exc:
            logger.error("Batch error: %s", exc)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            finished_at = utc_now()
            save_status(
                {
                    "service": WORKER_NAME,
                    "status": "error",
                    "last_cycle_started_at": started_at,
                    "last_cycle_finished_at": finished_at,
                    "last_error": str(exc),
                    "items_processed": enriched_count,
                    "items_remaining": max(0, len(pending) - enriched_count - skipped_count),
                    **provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown),
                    "concurrency": concurrency,
                    "batch_size": settings["batch_size"],
                    "rate_limit_per_minute": fallback_requests_per_minute,
                    "nvidia_rate_limit_per_minute": nvidia_requests_per_minute,
                    "email_strategy": settings.get("email_strategy", ENRICH_EMAIL_STRATEGY),
                    "enrich_categories": settings.get("enrich_categories", ENRICH_CATEGORIES),
                    "updated_at": finished_at,
                }
            )
            return True

    finished_at = utc_now()
    save_status(
        {
            "service": WORKER_NAME,
            "status": "idle",
            "last_cycle_started_at": started_at,
            "last_cycle_finished_at": finished_at,
            "last_success_at": finished_at,
            "items_processed": enriched_count,
            "items_remaining": max(0, len(pending) - enriched_count - skipped_count),
            **provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown),
            "concurrency": concurrency,
            "batch_size": settings["batch_size"],
            "rate_limit_per_minute": fallback_requests_per_minute,
            "nvidia_rate_limit_per_minute": nvidia_requests_per_minute,
            "email_strategy": settings.get("email_strategy", ENRICH_EMAIL_STRATEGY),
            "enrich_categories": settings.get("enrich_categories", ENRICH_CATEGORIES),
            "updated_at": finished_at,
        }
    )
    return True


def main():
    while True:
        try:
            processed = asyncio.run(enrich_batch())
            if not processed:
                time.sleep(load_settings()["sleep_interval"])
        except Exception as exc:
            logger.error("Cycle error: %s", exc)
            finished_at = utc_now()
            try:
                settings = load_settings()
                secrets = load_secrets()
                primary_cooldown = PrimaryCooldownState()
                fallback_cooldown = FallbackCooldownState()
                provider_fields = provider_status_fields(settings, secrets, primary_cooldown, fallback_cooldown)
            except Exception:
                provider_fields = {}
            save_status(
                {
                    "service": "enricher-worker",
                    "status": "error",
                    "last_cycle_started_at": finished_at,
                    "last_cycle_finished_at": finished_at,
                    "last_error": str(exc),
                    **provider_fields,
                    "updated_at": finished_at,
                }
            )
            time.sleep(load_settings()["sleep_interval"])


if __name__ == "__main__":
    main()
