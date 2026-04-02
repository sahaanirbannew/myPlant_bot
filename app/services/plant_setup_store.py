"""Plant setup extraction and persistence helpers for Telegram conversations."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from my_plants.file_manager import FileManager, PLANT_HEADERS, ROOM_HEADERS
from my_plants.utils import make_id


class PlantSetupStore:
    """Task: Persist static plant and room setup details inferred from Telegram conversations.
    Input: Gemini-extracted setup payloads plus a file-backed workspace rooted at the My Plants package.
    Output: Upserted plant and room records in the existing CSV files plus setup summaries for prompting.
    Failures: Malformed extraction payloads or filesystem issues can raise parsing and IO exceptions.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """Task: Initialize the setup store using paths relative to the repository workspace.
        Input: An optional base directory override pointing at the My Plants package root.
        Output: A ready-to-use PlantSetupStore instance.
        Failures: No failure is expected during construction.
        """

        package_root = base_dir or Path(__file__).resolve().parents[2] / "my_plants"
        self.file_manager = FileManager(package_root)

    def extract_json_payload(self, raw_text: str) -> dict[str, Any]:
        """Task: Parse a Gemini response that should contain a JSON setup payload.
        Input: The raw text returned by Gemini, optionally wrapped in code fences.
        Output: A normalized dictionary with `plants` and `rooms` lists.
        Failures: Raises ValueError when valid JSON cannot be extracted.
        """

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("Plant setup payload must be a JSON object.")
        payload.setdefault("plants", [])
        payload.setdefault("rooms", [])
        return payload

    def upsert_setup_payload(self, user_id: int, payload: dict[str, Any], timestamp: str | None = None) -> list[dict[str, Any]]:
        """Task: Upsert extracted room and plant setup details into the existing CSV files.
        Input: The Telegram user id, a normalized setup payload, and an optional timestamp.
        Output: A list of persisted write summaries describing the file path, agent, and saved data.
        Failures: Raises IO or value errors if persistence fails or required values are invalid.
        """

        self.file_manager.ensure_workspace()
        saved_at = timestamp or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        user_key = str(user_id)
        rooms = self.file_manager.read_csv(self.file_manager.rooms_csv_path)
        plants = self.file_manager.read_csv(self.file_manager.plants_csv_path)
        write_summaries: list[dict[str, Any]] = []

        room_id_by_name: dict[str, str] = {}
        for room_payload in payload.get("rooms", []):
            room_row, was_updated = self._upsert_room(user_key=user_key, rooms=rooms, room_payload=room_payload)
            room_id_by_name[room_row["name"].lower()] = room_row["id"]
            write_summaries.append(
                {
                    "agent": "setup_memory_agent",
                    "file_path": str(self.file_manager.rooms_csv_path),
                    "saved_data": {**room_row, "write_mode": "updated" if was_updated else "created"},
                }
            )

        for plant_payload in payload.get("plants", []):
            plant_row, was_updated = self._upsert_plant(
                user_key=user_key,
                plants=plants,
                plant_payload=plant_payload,
                room_id_by_name=room_id_by_name,
                timestamp=saved_at,
            )
            write_summaries.append(
                {
                    "agent": "setup_memory_agent",
                    "file_path": str(self.file_manager.plants_csv_path),
                    "saved_data": {**plant_row, "write_mode": "updated" if was_updated else "created"},
                }
            )

        self.file_manager.write_csv(self.file_manager.rooms_csv_path, rooms, ROOM_HEADERS)
        self.file_manager.write_csv(self.file_manager.plants_csv_path, plants, PLANT_HEADERS)
        return write_summaries

    def build_user_setup_summary(self, user_id: int) -> str:
        """Task: Summarize the saved static setup context for one user for prompt injection.
        Input: The Telegram user id whose plant and room setup should be summarized.
        Output: A concise text summary of known plants and rooms, or a note that setup is missing.
        Failures: File IO issues can raise exceptions when reading CSV data.
        """

        self.file_manager.ensure_workspace()
        user_key = str(user_id)
        plants = [row for row in self.file_manager.read_csv(self.file_manager.plants_csv_path) if row["user_id"] == user_key]
        rooms = [row for row in self.file_manager.read_csv(self.file_manager.rooms_csv_path) if row["user_id"] == user_key]
        room_map = {room["id"]: room for room in rooms}

        if not plants and not rooms:
            return "No saved plant setup information yet."

        parts: list[str] = []
        if rooms:
            room_bits = []
            for room in rooms[:5]:
                room_bits.append(
                    ", ".join(
                        bit
                        for bit in [
                            room.get("name", ""),
                            room.get("type", ""),
                            f"{room.get('window_direction')} window" if room.get("window_direction") else "",
                            room.get("city", ""),
                            f"grow light={room.get('has_grow_light')}" if room.get("has_grow_light") else "",
                            f"size={room.get('size_sqft')} sqft" if room.get("size_sqft") else "",
                        ]
                        if bit
                    )
                )
            parts.append("Saved rooms: " + " | ".join(room_bits))

        if plants:
            plant_bits = []
            for plant in plants[:8]:
                room = room_map.get(plant.get("room_id", ""), {})
                plant_bits.append(
                    ", ".join(
                        bit
                        for bit in [
                            plant.get("name", ""),
                            f"species={plant.get('species')}" if plant.get("species") else "",
                            f"position={plant.get('position_in_room')}" if plant.get("position_in_room") else "",
                            f"soil={plant.get('soil_type')}" if plant.get("soil_type") else "",
                            f"fertilizer={plant.get('fertilizer_type')}" if plant.get("fertilizer_type") else "",
                            f"room={room.get('name')}" if room.get("name") else "",
                        ]
                        if bit
                    )
                )
            parts.append("Saved plants: " + " | ".join(plant_bits))

        return "\n".join(parts)

    def next_missing_setup_question(self, user_id: int) -> str | None:
        """Task: Determine one concise follow-up question that can gather missing static setup information.
        Input: The Telegram user id whose stored setup should be inspected.
        Output: A short question string, or None when enough setup detail is already available.
        Failures: File IO issues can raise exceptions while reading saved data.
        """

        self.file_manager.ensure_workspace()
        user_key = str(user_id)
        plants = [row for row in self.file_manager.read_csv(self.file_manager.plants_csv_path) if row["user_id"] == user_key]
        rooms = [row for row in self.file_manager.read_csv(self.file_manager.rooms_csv_path) if row["user_id"] == user_key]

        if not plants:
            return "What plants do you have at home right now?"

        for plant in plants:
            if not plant.get("species"):
                return f"What species is your {plant.get('name', 'plant')}?"
            if not plant.get("position_in_room"):
                return f"Where exactly do you keep your {plant.get('name', 'plant')} in the room?"
            if not plant.get("soil_type"):
                return f"What soil mix is your {plant.get('name', 'plant')} in?"
            if not plant.get("fertilizer_type"):
                return f"What fertilizer do you use for your {plant.get('name', 'plant')}?"

        for room in rooms:
            if not room.get("window_direction"):
                return f"Which direction does the light come from in {room.get('name', 'that room')}?"
            if not room.get("city"):
                return f"Which city is {room.get('name', 'that room')} in?"
            if not room.get("size_sqft"):
                return f"About how big is {room.get('name', 'that room')} in square feet?"
            if room.get("has_grow_light", "").lower() not in {"true", "false"}:
                return f"Does {room.get('name', 'that room')} have a grow light?"

        return None

    def _upsert_room(self, user_key: str, rooms: list[dict[str, str]], room_payload: dict[str, Any]) -> tuple[dict[str, str], bool]:
        """Task: Create or update one room row from an extracted room payload.
        Input: The user id, mutable room rows list, and one extracted room payload.
        Output: The persisted room row plus a boolean indicating whether it was updated.
        Failures: No failure is expected; missing optional fields are saved as empty strings.
        """

        room_name = str(room_payload.get("name") or room_payload.get("type") or "Plant Room").strip()
        existing_room = next(
            (
                room
                for room in rooms
                if room["user_id"] == user_key and room["name"].lower() == room_name.lower()
            ),
            None,
        )
        normalized = {
            "id": existing_room["id"] if existing_room else make_id("room"),
            "user_id": user_key,
            "name": room_name,
            "type": str(room_payload.get("type", "")).strip(),
            "window_direction": str(room_payload.get("window_direction", "")).strip(),
            "size_sqft": str(room_payload.get("size_sqft", "")).strip(),
            "has_grow_light": self._normalize_bool(room_payload.get("has_grow_light")),
            "city": str(room_payload.get("city", "")).strip(),
        }
        if existing_room is None:
            rooms.append(normalized)
            return normalized, False

        for key, value in normalized.items():
            if key in {"id", "user_id", "name"}:
                continue
            if value:
                existing_room[key] = value
        return existing_room, True

    def _upsert_plant(
        self,
        user_key: str,
        plants: list[dict[str, str]],
        plant_payload: dict[str, Any],
        room_id_by_name: dict[str, str],
        timestamp: str,
    ) -> tuple[dict[str, str], bool]:
        """Task: Create or update one plant row from an extracted plant payload.
        Input: The user id, mutable plant rows list, one extracted plant payload, room lookup, and timestamp.
        Output: The persisted plant row plus a boolean indicating whether it was updated.
        Failures: No failure is expected; missing optional fields are saved as empty strings.
        """

        plant_name = str(plant_payload.get("name") or plant_payload.get("species") or "Plant").strip()
        species = str(plant_payload.get("species") or plant_name).strip()
        existing_plant = next(
            (
                plant
                for plant in plants
                if plant["user_id"] == user_key and plant["name"].lower() == plant_name.lower()
            ),
            None,
        )
        room_name = str(plant_payload.get("room_name", "")).strip().lower()
        room_id = room_id_by_name.get(room_name, existing_plant.get("room_id", "") if existing_plant else "")
        normalized = {
            "id": existing_plant["id"] if existing_plant else make_id("plant"),
            "user_id": user_key,
            "name": plant_name,
            "species": species,
            "room_id": room_id,
            "position_in_room": str(plant_payload.get("position_in_room", "")).strip(),
            "soil_type": str(plant_payload.get("soil_type", "")).strip(),
            "fertilizer_type": str(plant_payload.get("fertilizer_type", "")).strip(),
            "created_at": existing_plant["created_at"] if existing_plant else timestamp,
        }
        if existing_plant is None:
            plants.append(normalized)
            return normalized, False

        for key, value in normalized.items():
            if key in {"id", "user_id", "created_at"}:
                continue
            if value:
                existing_plant[key] = value
        return existing_plant, True

    def _normalize_bool(self, value: Any) -> str:
        """Task: Normalize grow-light values into the stored lowercase boolean string format.
        Input: A raw value from extracted room payloads.
        Output: `true`, `false`, or an empty string.
        Failures: No failure is expected.
        """

        lowered = str(value).strip().lower()
        if lowered in {"true", "yes", "1"}:
            return "true"
        if lowered in {"false", "no", "0"}:
            return "false"
        return ""
