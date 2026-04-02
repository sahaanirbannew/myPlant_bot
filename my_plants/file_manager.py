"""File system utilities for the My Plants backend."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable


PLANT_HEADERS = [
    "id",
    "user_id",
    "name",
    "species",
    "room_id",
    "position_in_room",
    "soil_type",
    "fertilizer_type",
    "created_at",
]

ROOM_HEADERS = [
    "id",
    "user_id",
    "name",
    "type",
    "windows",
    "size_sqft",
    "has_grow_light",
    "city",
]

EVENT_HEADERS = [
    "event_id",
    "plant_id",
    "event_type",
    "subtype",
    "value",
    "metadata",
    "timestamp",
    "source",
]

DEFAULT_REQUIREMENTS = {
    "generic": {
        "watering_interval_days": 7,
        "light_preference": "medium",
        "notes": ["Check soil dryness before watering."],
    },
    "snake plant": {
        "watering_interval_days": 14,
        "light_preference": "low_to_medium",
        "notes": ["Allow soil to dry well between waterings."],
    },
    "pothos": {
        "watering_interval_days": 7,
        "light_preference": "medium",
        "notes": ["Keep out of harsh direct afternoon sun."],
    },
    "peace lily": {
        "watering_interval_days": 5,
        "light_preference": "low_to_medium",
        "notes": ["This plant likes slightly more regular moisture."],
    },
}

DEFAULT_CITY_PROFILES = {
    "default": {
        "humidity": "medium",
        "temperature_band": "moderate",
    },
    "bangalore": {
        "humidity": "medium",
        "temperature_band": "moderate",
    },
    "chennai": {
        "humidity": "high",
        "temperature_band": "hot",
    },
    "delhi": {
        "humidity": "low",
        "temperature_band": "hot",
    },
    "mumbai": {
        "humidity": "high",
        "temperature_band": "warm",
    },
    "pune": {
        "humidity": "medium",
        "temperature_band": "warm",
    },
}


class FileManager:
    """Task: Manage directory creation and file IO for the My Plants backend.
    Input: A base directory that contains the app script and all persistent folders.
    Output: Convenience methods for CSV, JSON, and text file operations.
    Failures: File permission errors or malformed content can raise OSError, csv.Error, or json.JSONDecodeError.
    """

    def __init__(self, base_dir: Path) -> None:
        """Task: Initialize the file manager with paths relative to the script location.
        Input: The base directory where the My Plants package lives.
        Output: A ready-to-use FileManager instance with known root file paths.
        Failures: No failure is expected unless a non-path-like argument is supplied.
        """

        self.base_dir = base_dir
        self.data_dir = base_dir / "data"
        self.requirements_json_path = self.data_dir / "plant_requirements.json"
        self.city_profiles_json_path = self.data_dir / "city_profiles.json"

    def user_dir(self, user_id: str) -> Path:
        """Task: Resolve the isolated directory boundary for a single user."""
        return self.data_dir / "users" / str(user_id)

    def plants_csv_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "plants.csv"

    def rooms_csv_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "rooms.csv"

    def events_csv_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "events.csv"

    def user_memory_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "memory.json"

    def raw_log_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "raw.log"

    def conversation_state_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "conversation_state.json"

    def conversation_history_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "conversation_history.json"

    def load_conversation_state(self, user_id: str) -> dict[str, Any] | None:
        """Task: Load the active conversation state. Returns None if it doesn't exist."""
        path = self.conversation_state_path(user_id)
        if not path.exists():
            return None
        state = self.read_json(path, default={})
        return state if state else None

    def save_conversation_state(self, user_id: str, state: dict[str, Any]) -> None:
        """Task: Write the conversation state payload to JSON."""
        self.write_json(self.conversation_state_path(user_id), state)

    def clear_conversation_state(self, user_id: str) -> None:
        """Task: Delete the conversation state file to clear the active flow."""
        path = self.conversation_state_path(user_id)
        if path.exists():
            path.unlink()

    def load_conversation_history(self, user_id: str) -> list[dict[str, str]]:
        """Task: Load the conversation history for a user, returning an empty list if absent."""
        path = self.conversation_history_path(user_id)
        if not path.exists():
            return []
        return self.read_json(path, default=[])

    def append_conversation(self, user_id: str, role: str, message: str) -> None:
        """Task: Append a message to the conversation history, keeping only the last 20 messages.
        Input: The user ID, role ('user' or 'bot'), and the raw message string.
        Output: Disk updated with the modified truncated list.
        """
        history = self.load_conversation_history(user_id)
        history.append({"role": role, "message": message})
        history = history[-20:]
        self.write_json(self.conversation_history_path(user_id), history)

    def ensure_workspace(self) -> None:
        """Task: Create global required directory and seed-file structure when absent.
        Input: No direct arguments; uses the configured base directory.
        Output: Required folders and starter config files exist on disk.
        Failures: Raises OSError if directories or files cannot be created.
        """

        self.data_dir.mkdir(parents=True, exist_ok=True)

        if not self.requirements_json_path.exists():
            self.write_json(self.requirements_json_path, DEFAULT_REQUIREMENTS)
        if not self.city_profiles_json_path.exists():
            self.write_json(self.city_profiles_json_path, DEFAULT_CITY_PROFILES)

    def ensure_user_workspace(self, user_id: str) -> None:
        """Task: Create per-user required directory and starter files.
        Input: The string user_id.
        Output: User's folder and empty state files created.
        Failures: Raises OSError.
        """
        
        user_dir = self.user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_csv_file(self.plants_csv_path(user_id), PLANT_HEADERS)
        self._ensure_csv_file(self.rooms_csv_path(user_id), ROOM_HEADERS)
        self._ensure_csv_file(self.events_csv_path(user_id), EVENT_HEADERS)

    def read_csv(self, path: Path) -> list[dict[str, str]]:
        """Task: Read structured rows from a CSV file into dictionaries.
        Input: The CSV file path to read.
        Output: A list of row dictionaries keyed by the CSV header fields.
        Failures: Raises OSError if the file cannot be opened or csv.Error if parsing fails.
        """

        if not path.exists():
            return []
        with path.open("r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            return [dict(row) for row in reader]

    def write_csv(self, path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
        """Task: Replace a CSV file with the provided rows using a strict header order.
        Input: The target file path, iterable rows, and required header field names.
        Output: A fully rewritten CSV file.
        Failures: Raises OSError if the file is unwritable.
        """

        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    def append_csv(self, path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
        """Task: Append a single row to a CSV file, creating the header if needed.
        Input: The target file path, a row dictionary, and the strict header field names.
        Output: The new row appended to the CSV file.
        Failures: Raises OSError if the file cannot be written.
        """

        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    def read_json(self, path: Path, default: Any) -> Any:
        """Task: Read JSON content or return a default value when the file is missing.
        Input: The JSON path to read and a default fallback value.
        Output: The decoded JSON object or the provided default.
        Failures: Raises OSError or json.JSONDecodeError if the existing file is unreadable or malformed.
        """

        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as json_file:
            return json.load(json_file)

    def write_json(self, path: Path, payload: Any) -> None:
        """Task: Persist JSON payloads using UTF-8 and readable formatting.
        Input: The target JSON file path and the serializable payload.
        Output: A JSON file written to disk.
        Failures: Raises OSError if the file cannot be written or TypeError if the payload is not serializable.
        """

        with path.open("w", encoding="utf-8") as json_file:
            json.dump(payload, json_file, indent=2, sort_keys=True)

    def append_text(self, path: Path, content: str) -> None:
        """Task: Append plain text to a log file.
        Input: The target text file path and the text content to append.
        Output: The content appended to the text file.
        Failures: Raises OSError if the file cannot be written.
        """

        with path.open("a", encoding="utf-8") as text_file:
            text_file.write(content)



    def _ensure_csv_file(self, path: Path, headers: list[str]) -> None:
        """Task: Create a CSV file with headers if it does not already exist.
        Input: The CSV file path and its strict header list.
        Output: A header-only CSV file when the target did not exist.
        Failures: Raises OSError if the file cannot be created.
        """

        if path.exists():
            return
        self.write_csv(path, [], headers)
