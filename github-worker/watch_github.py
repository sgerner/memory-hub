import base64
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STATE_PATH = "/app/config/state.json"
SETTINGS_PATH = "/app/config/settings.json"
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/github-worker.json")
SECRETS_PATH = os.getenv("SECRETS_PATH", "/app/shared-settings/secrets.json")

AGENTMEMORY_URL = os.getenv("AGENTMEMORY_URL", "http://agentmemory:3111")
AGENTMEMORY_TOKEN = os.getenv("AGENTMEMORY_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "").strip() or "unknown"
DEFAULT_SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "3600"))

SOURCE_EXTENSIONS = {
    '.svelte', '.ts', '.tsx', '.js', '.jsx', '.py',
    '.sh', '.yml', '.yaml', '.sql', '.json', '.md',
    '.html', '.css', '.conf', '.dockerfile', 'Dockerfile'
}

IGNORE_DIRS = {'node_modules', '.git', '.github', 'dist', 'build', 'vending', 'vendor', '__pycache__', '.svelte-kit'}

github_session = requests.Session()
memory_session = requests.Session()
if AGENTMEMORY_TOKEN:
    memory_session.headers.update({"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_status(status):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    temp_path = f"{STATUS_PATH}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as handle:
        json.dump(status, handle)
    os.replace(temp_path, STATUS_PATH)


def load_json(path, fallback):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        return fallback
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error("Could not load %s: %s", path, exc)
        return fallback


def load_settings():
    settings = {"sleep_interval": DEFAULT_SLEEP_INTERVAL, "content_limit": 100000, "issues_per_repo": 50}
    configured = load_json(SETTINGS_PATH, {})
    for key in settings:
        if key in configured:
            settings[key] = int(configured[key])
    return settings


def load_github_token():
    secrets = load_json(SECRETS_PATH, {})
    secret_token = str(secrets.get('github_token', '')).strip()
    return secret_token or os.getenv("GITHUB_TOKEN", "").strip()


def save_state(state):
    temp_path = f"{STATE_PATH}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as handle:
        json.dump(state, handle)
    os.replace(temp_path, STATE_PATH)


def github_api_get(url, token):
    try:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {token}",
        }
        response = github_session.get(url, headers=headers, timeout=20)
        if response.status_code == 403 and 'rate limit' in response.text.lower():
            logger.warning("GitHub rate limit hit. Waiting...")
            time.sleep(60)
            return None
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.error("GitHub API error on %s: %s", url, exc)
        return None


def push_to_memory(uid, title, content, category, metadata, content_limit):
    try:
        payload = {
            "content": f"Title: {title}\n\n{content[:content_limit]}",
            "category": category,
            "metadata": {
                **metadata,
                "uid": str(uid),
                "needs_enrichment": True,
                "source": "github",
            },
        }

        response = memory_session.post(f"{AGENTMEMORY_URL}/remember", json=payload, timeout=35)
        if response.status_code not in (200, 201):
            logger.error("Agentmemory error %s: %s", response.status_code, response.text)
            return False
        return True
    except Exception as exc:
        logger.error("Failed to push to memory: %s", exc)
        return False


def index_repo_content(repo, state, settings, token):
    repo_name = repo['full_name']
    repo_id = str(repo['id'])
    last_pushed = repo['pushed_at']

    if state.get(f"repo_meta_{repo_id}") == last_pushed:
        logger.info("Skipping content scan for %s (no new pushes)", repo_name)
        return 0

    logger.info("Deep scanning repository: %s...", repo_name)
    branch = repo.get('default_branch', 'main')
    tree_data = github_api_get(f"https://api.github.com/repos/{repo_name}/git/trees/{branch}?recursive=1", token)
    if not tree_data:
        return 0

    files_indexed = 0
    for item in tree_data.get('tree', []):
        if item['type'] != 'blob':
            continue

        path = item['path']
        if any(ignore in path.split('/') for ignore in IGNORE_DIRS):
            continue

        ext = os.path.splitext(path)[1].lower()
        filename = os.path.basename(path)
        if ext not in SOURCE_EXTENSIONS and filename not in SOURCE_EXTENSIONS:
            continue

        sha = item['sha']
        file_state_key = f"file_{repo_id}_{path}"
        if state.get(file_state_key) == sha:
            continue

        file_data = github_api_get(f"https://api.github.com/repos/{repo_name}/git/blobs/{sha}", token)
        if file_data and 'content' in file_data:
            try:
                raw_content = base64.b64decode(file_data['content']).decode('utf-8', errors='ignore')
                metadata = {
                    "repo": repo_name,
                    "path": path,
                    "sha": sha,
                    "language": repo.get('language'),
                    "type": "source_code",
                }

                if push_to_memory(f"{repo_id}_{sha}", f"File: {path} ({repo_name})", raw_content, "code", metadata, settings["content_limit"]):
                    state[file_state_key] = sha
                    files_indexed += 1
            except Exception as exc:
                logger.error("Error decoding/pushing %s: %s", path, exc)

    state[f"repo_meta_{repo_id}"] = last_pushed
    return files_indexed


def index_issues_and_prs(repo, state, settings, token):
    repo_name = repo['full_name']
    logger.info("Checking issues and PRs for %s...", repo_name)

    issues = github_api_get(
        f"https://api.github.com/repos/{repo_name}/issues?state=all&per_page={settings['issues_per_repo']}",
        token,
    )
    if not issues:
        return 0

    indexed = 0
    for issue in issues:
        issue_id = f"issue_{issue['id']}"
        updated_at = issue['updated_at']
        if state.get(issue_id) == updated_at:
            continue

        is_pr = 'pull_request' in issue
        type_str = "Pull Request" if is_pr else "Issue"
        content = f"{type_str} #{issue['number']}: {issue['title']}\n"
        content += f"Status: {issue['state']}\n"
        content += f"Author: {issue['user']['login']}\n\n"
        content += f"Description:\n{issue.get('body', 'No description provided.')}\n"

        metadata = {
            "repo": repo_name,
            "number": issue['number'],
            "type": "github_discussion",
            "is_pr": is_pr,
            "url": issue['html_url'],
        }

        if push_to_memory(issue_id, f"{type_str} #{issue['number']} in {repo_name}", content, "code", metadata, settings["content_limit"]):
            state[issue_id] = updated_at
            indexed += 1

    return indexed


def main():
    while True:
        settings = load_settings()
        token = load_github_token()

        if not token:
            logger.error("GitHub token missing. Sleeping...")
            save_status({
                "service": "github-worker",
                "status": "waiting",
                "last_cycle_started_at": utc_now(),
                "last_cycle_finished_at": utc_now(),
                "last_error": "GitHub token missing.",
                "updated_at": utc_now(),
            })
            time.sleep(settings["sleep_interval"])
            continue

        logger.info("Starting GitHub deep index cycle...")
        state = load_json(STATE_PATH, {})
        started_at = utc_now()
        repos_scanned = 0
        files_indexed = 0
        discussions_indexed = 0

        save_status({
            "service": "github-worker",
            "status": "running",
            "last_cycle_started_at": started_at,
            "updated_at": started_at,
            "primary_provider": "github",
            "source": GITHUB_USERNAME,
        })

        repos = github_api_get("https://api.github.com/user/repos?affiliation=owner&sort=updated", token)
        if repos:
            for repo in repos:
                try:
                    repos_scanned += 1
                    files_indexed += index_repo_content(repo, state, settings, token)
                    discussions_indexed += index_issues_and_prs(repo, state, settings, token)
                except Exception as exc:
                    logger.error("Failed to process repo %s: %s", repo.get('full_name', 'unknown'), exc)

            save_state(state)

        finished_at = utc_now()
        save_status({
            "service": "github-worker",
            "status": "idle",
            "last_cycle_started_at": started_at,
            "last_cycle_finished_at": finished_at,
            "last_success_at": finished_at,
            "items_processed": files_indexed + discussions_indexed,
            "details": {
                "repos_scanned": repos_scanned,
                "files_indexed": files_indexed,
                "discussions_indexed": discussions_indexed,
                "source": GITHUB_USERNAME,
            },
            "updated_at": finished_at,
        })

        logger.info(
            "Cycle complete. Indexed %s new files and %s discussions.",
            files_indexed,
            discussions_indexed,
        )

        logger.info("Sleeping for %s seconds...", settings["sleep_interval"])
        time.sleep(settings["sleep_interval"])


if __name__ == "__main__":
    main()
