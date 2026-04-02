"""Context assembly for deterministic plant-care decisions."""

from __future__ import annotations

from typing import Any

from my_plants.file_manager import FileManager


class ContextBuilder:
    """Task: Build a unified dictionary of plant, room, memory, event, and requirement data.
    Input: The file manager, current user id, and the target plant id.
    Output: A combined context dictionary used by analysis and decision rules.
    Failures: Malformed files can raise file or decode errors during load.
    """

    def __init__(self, file_manager: FileManager) -> None:
        """Task: Initialize the context builder with a file manager dependency.
        Input: A configured FileManager instance.
        Output: A ready-to-use ContextBuilder.
        Failures: No failure is expected.
        """

        self.file_manager = file_manager

    def build(self, user_id: str, plant_id: str | None) -> dict[str, Any]:
        """Task: Load persistent data and assemble the active decision context.
        Input: The user id and optional target plant id.
        Output: A dictionary containing plants, rooms, recent events, memory, and requirements.
        Failures: File read or decode errors can interrupt context assembly.
        """

        plants = self.file_manager.read_csv(self.file_manager.plants_csv_path)
        rooms = self.file_manager.read_csv(self.file_manager.rooms_csv_path)
        events = self.file_manager.read_csv(self.file_manager.events_csv_path)
        memory = self.file_manager.read_json(self.file_manager.user_memory_path(user_id), default={})
        requirements = self.file_manager.read_json(self.file_manager.requirements_json_path, default={})
        city_profiles = self.file_manager.read_json(self.file_manager.city_profiles_json_path, default={})

        plant = next((row for row in plants if row["id"] == plant_id), None) if plant_id else None
        room = None
        if plant and plant.get("room_id"):
            room = next((row for row in rooms if row["id"] == plant["room_id"]), None)

        plant_events = [event for event in events if not plant_id or event["plant_id"] == plant_id]
        recent_events = plant_events[-20:]
        requirement_key = plant["species"].lower() if plant else "generic"
        plant_requirements = requirements.get(requirement_key, requirements.get("generic", {}))

        return {
            "plant": plant,
            "room": room,
            "plants": plants,
            "rooms": rooms,
            "all_plant_events": plant_events,
            "recent_events": recent_events,
            "memory": memory,
            "plant_requirements": plant_requirements,
            "city_profiles": city_profiles,
        }
