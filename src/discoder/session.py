"""Session management: maps Discord threads to Claude Code sessions."""

import json
import logging
from pathlib import Path

from .config import CONFIG_DIR

logger = logging.getLogger(__name__)

SESSIONS_FILE = CONFIG_DIR / "sessions.json"


class SessionStore:
    """Persistent mapping between Discord threads and Claude Code sessions."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._load()

    def reload(self):
        """Reload sessions from disk."""
        self._load()

    def _load(self):
        if SESSIONS_FILE.exists():
            try:
                self._sessions = json.loads(SESSIONS_FILE.read_text())
            except json.JSONDecodeError:
                self._sessions = {}

    def _save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_FILE.write_text(json.dumps(self._sessions, indent=2))

    def create(self, thread_key: str, session_id: str, cwd: str, model: str | None = None) -> None:
        """Register a new session. thread_key is 'channel_id:thread_ts'."""
        entry = {
            "session_id": session_id,
            "cwd": cwd,
        }
        if model:
            entry["model"] = model
        existing = self._sessions.get(thread_key)
        if existing and "model" in existing and not model:
            entry["model"] = existing["model"]
        self._sessions[thread_key] = entry
        self._save()
        logger.info(f"Session created: thread={thread_key} session={session_id}")

    def get_by_thread(self, thread_key: str) -> dict | None:
        """Get session info by Discord thread key."""
        return self._sessions.get(thread_key)

    def get_by_session_id(self, session_id: str) -> tuple[str, dict] | None:
        """Get thread key and session info by Claude session ID."""
        for key, info in self._sessions.items():
            if info["session_id"] == session_id:
                return key, info
        return None

    def set_model(self, thread_key: str, model: str) -> bool:
        """Set the model for a session."""
        if thread_key not in self._sessions:
            return False
        self._sessions[thread_key]["model"] = model
        self._save()
        return True

    def list_sessions(self) -> dict[str, dict]:
        """Return all sessions."""
        return dict(self._sessions)

    def remove(self, thread_key: str) -> None:
        """Remove a session."""
        self._sessions.pop(thread_key, None)
        self._save()

    def clear_all(self) -> None:
        """Remove all sessions."""
        self._sessions = {}
        self._save()
