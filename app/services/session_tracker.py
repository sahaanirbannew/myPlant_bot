"""Session wrapper that tracks daily quota and records finalized sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.session import UserSession


class SessionTracker:
    """Task: Track daily conversation limits and export expired sessions to files."""

    def __init__(self, quota_path: Path, sessions_dir: Path) -> None:
        self.quota_path = quota_path
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _read_quota(self) -> dict[str, Any]:
        if not self.quota_path.exists():
            return {}
        try:
            with self.quota_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_quota(self, data: dict[str, Any]) -> None:
        self.quota_path.parent.mkdir(parents=True, exist_ok=True)
        with self.quota_path.open("w", encoding="utf-8") as f:
            json.dump(data, f)

    def is_quota_exceeded(self, user_id: int, current_session: UserSession | None = None) -> bool:
        """Check if the user has talked for more than 30 minutes today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota = self._read_quota()
        user_record = quota.get(str(user_id), {"date": today, "elapsed_seconds": 0})
        
        if user_record["date"] != today:
            user_record = {"date": today, "elapsed_seconds": 0}

        # Calculate current session duration if active
        session_elapsed = 0
        if current_session:
            session_elapsed = (datetime.now(timezone.utc) - current_session.first_active_at).total_seconds()
        
        # If the total exceeds 30 minutes
        if user_record["elapsed_seconds"] + session_elapsed > 30 * 60:
            return True
        return False

    def update_quota_and_record_session(self, user_id: int, session: UserSession, history: list[dict[str, Any]]) -> None:
        """Update quota when session expires/clears, and record the session text."""
        # 1. Update Daily Quota
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota = self._read_quota()
        user_record = quota.get(str(user_id), {"date": today, "elapsed_seconds": 0})
        if user_record["date"] != today:
            user_record = {"date": today, "elapsed_seconds": 0}
            
        session_duration = (datetime.now(timezone.utc) - session.first_active_at).total_seconds()
        user_record["elapsed_seconds"] += session_duration
        quota[str(user_id)] = user_record
        self._write_quota(quota)

        # 2. Record Session
        if not history:
            return

        session_start_iso = session.first_active_at.strftime("%Y%m%d_%H%M%S")
        user_session_dir = self.sessions_dir / str(user_id)
        user_session_dir.mkdir(parents=True, exist_ok=True)
        
        record_path = user_session_dir / f"session_{session_start_iso}.txt"
        with record_path.open("w", encoding="utf-8") as f:
            f.write(f"Session Start: {session.first_active_at.isoformat()}\n")
            f.write(f"Session Duration: {session_duration:.1f} seconds\n")
            f.write("-" * 40 + "\n")
            for msg in history:
                timestamp = msg.get("timestamp", "")
                role = str(msg.get("role", "")).capitalize()
                text = msg.get("message", "")
                f.write(f"[{timestamp}] {role}: {text}\n")
