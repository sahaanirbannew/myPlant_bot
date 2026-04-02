"""In-memory session cache for active Telegram users."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.services.storage import UserKeyStore


@dataclass
class UserSession:
    """Task: Keep temporary in-memory state for an active Telegram user session.
    Input: The user's id, cached Gemini API key, last activity time, and setup state.
    Output: A mutable data object stored in the session manager.
    Failures: Stale timestamps or missing keys can force unnecessary reloading from disk.
    """

    user_id: int
    gemini_api_key: Optional[str]
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    awaiting_setup_key: bool = False


class SessionManager:
    """Task: Manage short-lived in-memory user sessions with inactivity expiry.
    Input: A CSV store for loading fallback Gemini API keys and a timeout value in seconds.
    Output: Session lookup, mutation, and cleanup helpers for the bot flow.
    Failures: Concurrency mistakes can create stale session state if methods are bypassed.
    """

    def __init__(self, key_store: UserKeyStore, timeout_seconds: int) -> None:
        """Task: Initialize the session manager with storage-backed fallback loading.
        Input: A UserKeyStore instance and inactivity timeout in seconds.
        Output: A ready-to-use SessionManager instance.
        Failures: Misconfigured timeout values can make sessions expire too early or too late.
        """

        self.key_store = key_store
        self.timeout_seconds = timeout_seconds
        self._sessions: Dict[int, UserSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_load_session(self, user_id: int) -> UserSession:
        """Task: Return an active session, loading the latest saved Gemini key when needed.
        Input: The user's numeric Telegram id.
        Output: A UserSession containing the current in-memory state for that user.
        Failures: Storage read failures can prevent the session from loading a saved key.
        """

        async with self._lock:
            session = self._sessions.get(user_id)
            if session is None:
                latest_key_record = self.key_store.fetch_latest_key(user_id)
                session = UserSession(
                    user_id=user_id,
                    gemini_api_key=latest_key_record.gemini_api_key if latest_key_record else None,
                )
                self._sessions[user_id] = session
            session.last_active_at = datetime.now(timezone.utc)
            return session

    async def mark_waiting_for_key(self, user_id: int) -> UserSession:
        """Task: Mark that a user is in the `/setup` flow and expected to send a Gemini API key next.
        Input: The user's numeric Telegram id.
        Output: The updated UserSession for that user.
        Failures: Storage read failures during lazy session loading can prevent setup state updates.
        """

        session = await self.get_or_load_session(user_id)
        async with self._lock:
            session.awaiting_setup_key = True
            session.last_active_at = datetime.now(timezone.utc)
            return session

    async def update_api_key(self, user_id: int, gemini_api_key: str) -> None:
        """Task: Update the in-memory Gemini API key after a successful setup flow.
        Input: The user's numeric Telegram id and a validated Gemini API key.
        Output: None; the active in-memory session is updated in place.
        Failures: Storage read failures during lazy session loading can prevent cache refresh.
        """

        session = await self.get_or_load_session(user_id)
        async with self._lock:
            session.gemini_api_key = gemini_api_key
            session.awaiting_setup_key = False
            session.last_active_at = datetime.now(timezone.utc)

    async def clear_api_key(self, user_id: int) -> None:
        """Task: Remove the cached Gemini API key from active memory for a user.
        Input: The user's numeric Telegram id.
        Output: None; the user session is cleared or removed from the cache.
        Failures: No failure is expected; missing sessions are ignored.
        """

        async with self._lock:
            self._sessions.pop(user_id, None)

    async def cleanup_expired_sessions(self) -> None:
        """Task: Remove sessions that have been inactive longer than the configured timeout.
        Input: No direct arguments; uses the current UTC time and configured timeout.
        Output: None; expired sessions are removed from memory.
        Failures: No failure is expected unless the internal session map is corrupted.
        """

        expiration_threshold = datetime.now(timezone.utc) - timedelta(seconds=self.timeout_seconds)
        async with self._lock:
            expired_user_ids = [
                user_id
                for user_id, session in self._sessions.items()
                if session.last_active_at < expiration_threshold
            ]
            for user_id in expired_user_ids:
                self._sessions.pop(user_id, None)

