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
        Output: A normalized dictionary with `plants`, `rooms`, and an optional clarification question.
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
        payload.setdefault("deleted_plants", [])
        payload.setdefault("deleted_rooms", [])
        payload.setdefault("clarification_question", "")
        return payload

    def upsert_setup_payload(self, user_id: int, payload: dict[str, Any], timestamp: str | None = None) -> list[dict[str, Any]]:
        """Task: Upsert extracted room and plant setup details into the existing CSV files.
        Input: The Telegram user id, a normalized setup payload, and an optional timestamp.
        Output: A list of persisted write summaries describing the file path, agent, and saved data.
        Failures: Raises IO or value errors if persistence fails or required values are invalid.
        """

        self.file_manager.ensure_user_workspace(user_id)
        saved_at = timestamp or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        user_key = str(user_id)
        rooms = self.file_manager.read_csv(self.file_manager.rooms_csv_path(user_key))
        plants = self.file_manager.read_csv(self.file_manager.plants_csv_path(user_key))
        write_summaries: list[dict[str, Any]] = []

        deleted_room_names = {str(r).lower() for r in payload.get("deleted_rooms", [])}
        deleted_plant_names = {str(p).lower() for p in payload.get("deleted_plants", [])}

        if deleted_room_names:
            filtered_rooms = []
            for r in rooms:
                if r.get("name", "").lower() in deleted_room_names:
                    write_summaries.append({
                        "agent": "setup_memory_agent",
                        "file_path": str(self.file_manager.rooms_csv_path(user_key)),
                        "saved_data": {**r, "write_mode": "deleted"},
                    })
                else:
                    filtered_rooms.append(r)
            rooms = filtered_rooms

        if deleted_plant_names:
            filtered_plants = []
            for p in plants:
                if p.get("name", "").lower() in deleted_plant_names or p.get("species", "").lower() in deleted_plant_names:
                    write_summaries.append({
                        "agent": "setup_memory_agent",
                        "file_path": str(self.file_manager.plants_csv_path(user_key)),
                        "saved_data": {**p, "write_mode": "deleted"},
                    })
                else:
                    filtered_plants.append(p)
            plants = filtered_plants


        room_id_by_name: dict[str, str] = {}
        for room_payload in payload.get("rooms", []):
            room_row, was_updated = self._upsert_room(user_key=user_key, rooms=rooms, room_payload=room_payload)
            room_id_by_name[room_row["name"].lower()] = room_row["id"]
            write_summaries.append(
                {
                    "agent": "setup_memory_agent",
                    "file_path": str(self.file_manager.rooms_csv_path(user_key)),
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
            
            room_row = next((r for r in rooms if r["id"] == plant_row["room_id"]), {})
            md_profile = (
                f"# Plant Profile: {plant_row['name']}\n\n"
                f"- **Species**: {plant_row.get('species', 'Unknown')}\n"
                f"- **Room Placed**: {room_row.get('name', 'Unknown')}\n"
                f"- **Room Windows**: {room_row.get('windows', 'Unknown')}\n"
                f"- **Room City**: {room_row.get('city', 'Unknown')}\n"
                f"- **Has Grow Light?**: {room_row.get('has_grow_light', 'Unknown')}\n"
                f"- **Exact Position in Room**: {plant_row.get('position_in_room', 'Unknown')}\n"
                f"- **Soil Type**: {plant_row.get('soil_type', 'Unknown')}\n"
                f"- **Fertilizer**: {plant_row.get('fertilizer_type', 'Unknown')}\n"
            )
            self.file_manager.write_plant_profile(user_key, plant_row["id"], md_profile)
            
            self.file_manager.append_plant_ledger_entry(
                user_id=user_key,
                plant_id=plant_row["id"],
                entry_type="profile_update",
                payload=plant_row,
                timestamp=saved_at,
            )

            write_summaries.append(
                {
                    "agent": "setup_memory_agent",
                    "file_path": str(self.file_manager.plants_csv_path(user_key)),
                    "saved_data": {**plant_row, "write_mode": "updated" if was_updated else "created"},
                }
            )

        self.file_manager.write_csv(self.file_manager.rooms_csv_path(user_key), rooms, ROOM_HEADERS)
        self.file_manager.write_csv(self.file_manager.plants_csv_path(user_key), plants, PLANT_HEADERS)
        return write_summaries

    def build_user_setup_summary(self, user_id: int, discussion_context: str = "") -> str:
        """Task: Summarize the saved static setup context for one user for prompt injection.
        Input: The Telegram user id and ongoing conversation text.
        Output: A concise text summary plus full markdown profiles of any plants actively discussed.
        Failures: File IO issues can raise exceptions when reading CSV data.
        """

        self.file_manager.ensure_user_workspace(user_id)
        user_key = str(user_id)
        plants = [row for row in self.file_manager.read_csv(self.file_manager.plants_csv_path(user_key)) if row["user_id"] == user_key]
        rooms = [row for row in self.file_manager.read_csv(self.file_manager.rooms_csv_path(user_key)) if row["user_id"] == user_key]
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
                            f"windows: {room.get('windows')}" if room.get("windows") else "",
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
                            f"soil={plant.get('soil_type')}" if plant.get("soil_type") else "",
                            f"fertilizer={plant.get('fertilizer_type')}" if plant.get("fertilizer_type") else "",
                            f"room={room.get('name')}" if room.get("name") else "",
                        ]
                        if bit
                    )
                )
            parts.append("Saved plants: " + " | ".join(plant_bits))

        if discussion_context and plants:
            context_lower = discussion_context.lower()
            topic_profiles: list[str] = []
            for plant in plants:
                name = plant.get("name", "").lower()
                species = plant.get("species", "").lower()
                if (name and len(name) > 2 and name in context_lower) or (species and len(species) > 2 and species in context_lower):
                    profile_content = self.file_manager.read_plant_profile(user_key, plant["id"])
                    if profile_content:
                        topic_profiles.append(profile_content)
            
            if topic_profiles:
                parts.append("\n=== RELEVANT PLANT PROFILES FOR CURRENT DISCUSSION ===")
                parts.extend(topic_profiles)
                parts.append("====================================================")

        return "\n".join(parts)

    def next_missing_setup_question(self, user_id: int) -> str | None:
        """Task: Determine one concise follow-up question that can gather missing static setup information.
        Input: The Telegram user id whose stored setup should be inspected.
        Output: A short question string, or None when enough setup detail is already available.
        Failures: File IO issues can raise exceptions while reading saved data.
        """

        self.file_manager.ensure_user_workspace(user_id)
        user_key = str(user_id)
        plants = [row for row in self.file_manager.read_csv(self.file_manager.plants_csv_path(user_key)) if row["user_id"] == user_key]
        rooms = [row for row in self.file_manager.read_csv(self.file_manager.rooms_csv_path(user_key)) if row["user_id"] == user_key]

        if not rooms:
            return "Before we add any plants, let's set up your environment. Which city are you in, and what room will you keep your plants in?"

        for room in rooms:
            if not room.get("windows"):
                return f"Which direction do the windows face in {room.get('name', 'that room')}?"
            if not room.get("city"):
                return f"Which city is {room.get('name', 'that room')} in?"
            if not room.get("size_sqft"):
                return f"About how big is {room.get('name', 'that room')} in square feet?"
            if not room.get("has_grow_light"):
                return f"Does {room.get('name', 'that room')} have a grow light?"

        if not plants:
            return "What plants do you have at home right now?"

        for plant in plants:
            if not plant.get("species"):
                return f"What species is your {plant.get('name', 'plant')}?"
            if not plant.get("soil_type"):
                return f"What soil mix is your {plant.get('name', 'plant')} in?"
            if not plant.get("fertilizer_type"):
                return f"What fertilizer do you use for your {plant.get('name', 'plant')}?"

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
            "windows": str(room_payload.get("windows", "")).strip(),
            "size_sqft": str(room_payload.get("size_sqft", "")).strip(),
            "has_grow_light": str(room_payload.get("has_grow_light", "")).strip(),
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

