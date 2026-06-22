import asyncio
import os
import time
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

AGENTMEMORY_URL = os.getenv("AGENTMEMORY_URL", "http://agentmemory:3111")
AGENTMEMORY_TOKEN = os.getenv("AGENTMEMORY_TOKEN", "memorex")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip()

def get_memories(category, limit=50):
    headers = {"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"}
    resp = requests.get(f"{AGENTMEMORY_URL}/memories/{category}?limit={limit}", headers=headers)
    if resp.status_code == 200:
        return resp.json().get("memories", [])
    return []

def store_reflection(content, related_to):
    headers = {"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"}
    payload = {
        "content": content,
        "category": "agent",
        "metadata": {"kind": "synthesis", "source": "reflection_worker"},
        "related_to": related_to
    }
    requests.post(f"{AGENTMEMORY_URL}/remember", json=payload, headers=headers)

async def synthesize_memories(memories):
    if not NVIDIA_API_KEY:
        logger.warning("No NVIDIA_API_KEY provided.")
        return None
    
    docs = "\n".join([f"- {m['id']}: {m['document']}" for m in memories])
    prompt = f"Synthesize these memories into broader concepts:\n{docs}\nProvide a concise summary of the key themes."
    
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.2
    }
    
    try:
        resp = requests.post(f"{NVIDIA_BASE_URL}/chat/completions", json=payload, headers=headers)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
    return None

async def worker_loop():
    while True:
        logger.info("Running reflection pass...")
        memories = get_memories("agent", limit=20)
        unreflected = [m for m in memories if not m.get("metadata", {}).get("reflected")]
        
        if len(unreflected) >= 5:
            logger.info(f"Reflecting on {len(unreflected)} memories...")
            summary = await synthesize_memories(unreflected)
            if summary:
                related = [str(m["id"]) for m in unreflected]
                store_reflection(summary, related)
                
                # Mark as reflected
                headers = {"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"}
                for m in unreflected:
                    requests.post(
                        f"{AGENTMEMORY_URL}/update",
                        json={"id": m["id"], "category": "agent", "metadata": {"reflected": True}},
                        headers=headers
                    )
                logger.info("Reflection stored.")
        
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(worker_loop())
