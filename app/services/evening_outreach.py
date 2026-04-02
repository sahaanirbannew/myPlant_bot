"""Evening outreach scheduling for proactive Telegram setup questions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")


class EveningOutreachStore:
    """Task: Track known Telegram chats and daily proactive outreach state using local JSON files.
    Input: File paths for the user registry and outreach schedule state.
    Output: Registered chat records plus deterministic daily outreach decisions.
    Failures: File IO or malformed JSON can raise exceptions during read and write operations.
    """

    def __init__(self, registry_path: Path, state_path: Path) -> None:
        """Task: Initialize the outreach store with registry and state JSON file paths.
        Input: Two file paths rooted in the local data directory.
        Output: A ready-to-use EveningOutreachStore instance.
        Failures: No failure is expected during construction.
        """

        self.registry_path = registry_path
        self.state_path = state_path

    def ensure_store_exists(self) -> None:
        """Task: Create the registry and state files if they do not already exist.
        Input: No direct arguments.
        Output: Empty JSON files on disk when needed.
        Failures: Raises OSError if the files cannot be created.
        """

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write_json(self.registry_path, {"users": {}})
        if not self.state_path.exists():
            self._write_json(self.state_path, {"last_sent": {}})

    def register_user(self, user_id: int, chat_id: int) -> dict[str, Any]:
        """Task: Store the chat id associated with a Telegram user for future proactive outreach.
        Input: The Telegram user id and chat id observed on an inbound message.
        Output: The normalized registry record for that user.
        Failures: Raises IO or JSON errors if the registry cannot be updated.
        """

        self.ensure_store_exists()
        payload = self._read_json(self.registry_path)
        record = payload.setdefault("users", {}).get(str(user_id), {})
        record.update({"user_id": user_id, "chat_id": chat_id, "updated_at": self._utc_now_string()})
        payload["users"][str(user_id)] = record
        self._write_json(self.registry_path, payload)
        return record

    def due_users(self, now_utc: datetime, time_slot_store: Any = None) -> list[dict[str, Any]]:
        """Task: Return users whose deterministic evening outreach time has passed and was not sent today.
        Input: The current UTC datetime used to evaluate local evening windows.
        Output: User registry records that should receive a proactive message now.
        Failures: Raises IO or JSON errors if the registry or state cannot be read.
        """

        self.ensure_store_exists()
        registry = self._read_json(self.registry_path).get("users", {})
        state = self._read_json(self.state_path).get("last_sent", {})
        now_local = now_utc.astimezone(LOCAL_TIMEZONE)
        today_key = now_local.strftime("%Y-%m-%d")

        due_records: list[dict[str, Any]] = []
        for user_key, record in registry.items():
            user_id = int(record["user_id"])
            if time_slot_store:
                start_hour, end_hour = time_slot_store.get_time_slot(user_id)
            else:
                start_hour, end_hour = 17, 19
            
            if now_local.hour < start_hour or now_local.hour >= end_hour:
                continue

            # Deterministic minute within the user's slot
            duration_minutes = (end_hour - start_hour) * 60
            scheduled_offset = sum(ord(character) for character in f"{user_key}:{today_key}") % duration_minutes
            
            current_minute_offset = (now_local.hour - start_hour) * 60 + now_local.minute
            if current_minute_offset < scheduled_offset:
                continue
            if state.get(user_key) == today_key:
                continue
            due_records.append(record)
        return due_records

    def mark_sent(self, user_id: int, date_key: str) -> None:
        """Task: Mark that a proactive evening message has already been sent to one user for one local day.
        Input: The Telegram user id and local date string.
        Output: The outreach state JSON updated on disk.
        Failures: Raises IO or JSON errors if the state file cannot be written.
        """

        self.ensure_store_exists()
        payload = self._read_json(self.state_path)
        payload.setdefault("last_sent", {})[str(user_id)] = date_key
        self._write_json(self.state_path, payload)

    def _scheduled_minute(self, user_key: str, date_key: str) -> int:
        """Task: Pick a deterministic pseudo-random minute between 5 PM and 7 PM for one user and day.
        Input: The string user id and local date key.
        Output: An integer minute offset within the 120-minute evening window.
        Failures: No failure is expected.
        """

        return sum(ord(character) for character in f"{user_key}:{date_key}") % 120

    def _read_json(self, path: Path) -> dict[str, Any]:
        """Task: Read a JSON object from disk.
        Input: The target JSON file path.
        Output: The decoded JSON object.
        Failures: Raises IO or JSON decode errors for unreadable or malformed files.
        """

        with path.open("r", encoding="utf-8") as json_file:
            return json.load(json_file)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        """Task: Persist a JSON object to disk using readable formatting.
        Input: The target JSON file path and payload dictionary.
        Output: The JSON file written to disk.
        Failures: Raises OSError or TypeError if the file cannot be written or the payload is not serializable.
        """

        with path.open("w", encoding="utf-8") as json_file:
            json.dump(payload, json_file, indent=2, sort_keys=True)

    def _utc_now_string(self) -> str:
        """Task: Return the current UTC timestamp string for registry updates.
        Input: No direct arguments.
        Output: A UTC timestamp string in ISO 8601 format.
        Failures: No failure is expected.
        """

        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
