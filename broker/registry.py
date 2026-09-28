"""
Tiny persisted registry of "connections" — each one represents an app/
integration that's allowed to have its own agent. Mirrors OIC's model:
you create a connection in the console, then download an agent installer
pre-configured for that connection.

Stored as a JSON file next to this module. Good enough for a demo /
small deployment; swap for a real DB if you need multi-instance brokers.
"""
import json
import os
import secrets
import threading
import time
from typing import Optional

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", os.path.join(os.path.dirname(__file__), "connections.json"))

_lock = threading.Lock()


def _load() -> dict:
    if not os.path.exists(REGISTRY_PATH):
        return {}
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


def _save(data: dict):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def list_connections() -> dict:
    with _lock:
        return _load()


def create_connection(label: str) -> dict:
    with _lock:
        data = _load()
        group = secrets.token_hex(4) + "-" + "".join(
            c.lower() if c.isalnum() else "-" for c in label
        )[:32].strip("-")
        token = secrets.token_urlsafe(24)
        entry = {
            "group": group,
            "label": label,
            "agent_token": token,
            "created_at": time.time(),
        }
        data[group] = entry
        _save(data)
        return entry


def get_connection(group: str) -> Optional[dict]:
    with _lock:
        return _load().get(group)


def delete_connection(group: str) -> bool:
    with _lock:
        data = _load()
        if group in data:
            del data[group]
            _save(data)
            return True
        return False


def verify_agent_token(group: str, token: str) -> bool:
    entry = get_connection(group)
    return bool(entry and secrets.compare_digest(entry["agent_token"], token))
