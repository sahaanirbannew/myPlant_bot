"""End-to-end deterministic orchestration for the My Plants assistant."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from my_plants.context_builder import ContextBuilder
from my_plants.conversation_agent import ConversationAgent
from my_plants.decision_engine import DecisionEngine
from my_plants.file_manager import EVENT_HEADERS, PLANT_HEADERS, ROOM_HEADERS, FileManager
from my_plants.memory_extractor import MemoryExtractor
from my_plants.plant_resolver import PlantResolver
from my_plants.reminder_agent import ReminderAgent
from my_plants.response_generator import ResponseGenerator
from my_plants.time_series_analyzer import TimeSeriesAnalyzer
from my_plants.watering_scheduler import WateringScheduler
from my_plants.utils import iso_now, make_id


class Orchestrator:
    """Task: Coordinate the full deterministic My Plants pipeline from input to response.
    Input: The backend dependencies that read files, extract structure, analyze history, and generate replies.
    Output: A single `handle` method that updates files and returns an assistant response.
    Failures: File or parsing errors can interrupt processing and raise exceptions.
    """

    def __init__(
        self,
        file_manager: FileManager,
        plant_resolver: PlantResolver,
        memory_extractor: MemoryExtractor,
        conversation_agent: ConversationAgent,
        context_builder: ContextBuilder,
        time_series_analyzer: TimeSeriesAnalyzer,
        watering_scheduler: WateringScheduler,
        decision_engine: DecisionEngine,
        reminder_agent: ReminderAgent,
        response_generator: ResponseGenerator,
    ) -> None:
        """Task: Initialize the orchestrator with all deterministic backend components.
        Input: Concrete component instances for each step in the pipeline.
        Output: A ready-to-use Orchestrator instance.
        Failures: No failure is expected unless invalid dependencies are provided.
        """

        self.file_manager = file_manager
        self.plant_resolver = plant_resolver
        self.memory_extractor = memory_extractor
        self.conversation_agent = conversation_agent
        self.context_builder = context_builder
        self.time_series_analyzer = time_series_analyzer
        self.watering_scheduler = watering_scheduler
        self.decision_engine = decision_engine
        self.reminder_agent = reminder_agent
        self.response_generator = response_generator

    def handle(self, user_id: str, message: str, now: datetime | None = None) -> str:
        """Task: Run the complete deterministic handling flow for a user message.
        Input: The user id, raw message text, and an optional datetime override for testing.
        Output: A conversational response string from the backend.
        Failures: File IO and timestamp parsing issues can raise runtime exceptions.
        """

        self.file_manager.ensure_workspace()
        timestamp = iso_now(now)
        self._log_raw_message(user_id=user_id, message=message, timestamp=timestamp)

        if self._is_reminder_query(message):
            return self.scan_due_plants(user_id=user_id, now=now)

        user_memory = self.file_manager.read_json(self.file_manager.user_memory_path(user_id), default={})
        plants = self.file_manager.read_csv(self.file_manager.plants_csv_path)
        resolution = self.plant_resolver.resolve(
            user_id=user_id,
            message=message,
            plants=plants,
            user_memory=user_memory,
            timestamp=timestamp,
        )

        if resolution["needs_clarification"]:
            self._write_memory(user_id=user_id, payload={**user_memory, "updated_at": timestamp})
            return "I could not determine which plant you mean yet. Mention the plant name or tell me you bought one."

        plant = resolution["plant"]
        if resolution["created"]:
            plants.append(plant)
            self.file_manager.write_csv(self.file_manager.plants_csv_path, plants, PLANT_HEADERS)

        rooms = self.file_manager.read_csv(self.file_manager.rooms_csv_path)
        conversation_result = self.conversation_agent.handle_pending_question(
            user_id=user_id,
            plant=plant,
            rooms=rooms,
            user_memory=user_memory,
            message=message,
            timestamp=timestamp,
        )
        if conversation_result.get("handled"):
            self._persist_rooms(conversation_result.get("rooms", rooms))
            self._persist_plant(conversation_result.get("plant", plant))
            self._write_memory(user_id=user_id, payload=conversation_result["memory"])
            return conversation_result["response"]

        extraction = self.memory_extractor.extract(message=message, timestamp=timestamp)
        plant = self._apply_room_facts(user_id=user_id, plant=plant, room_facts=extraction["room_facts"])
        self._persist_plant(plant=plant)
        self._persist_events(plant_id=plant["id"], extraction=extraction, timestamp=timestamp)

        memory_payload = {
            **user_memory,
            "last_used_plant_id": plant["id"],
            "last_message": message,
            "updated_at": timestamp,
        }
        if resolution["created"]:
            onboarding_result = self.conversation_agent.begin_profile_collection(
                plant=plant,
                user_memory=memory_payload,
                timestamp=timestamp,
            )
            self._write_memory(user_id=user_id, payload=onboarding_result["memory"])
            return onboarding_result["response"]

        self._write_memory(user_id=user_id, payload=memory_payload)

        context = self.context_builder.build(user_id=user_id, plant_id=plant["id"])
        analysis = self.time_series_analyzer.analyze(events=context["all_plant_events"], now_timestamp=timestamp)
        watering_schedule = self.watering_scheduler.compute(context=context, analysis=analysis)
        decisions = self.decision_engine.evaluate(context=context, analysis=analysis)
        latest_activity = self._summarize_recent_activity(context["recent_events"])
        return self.response_generator.generate(
            context=context,
            analysis=analysis,
            decisions=decisions,
            latest_activity=latest_activity,
            watering_schedule=watering_schedule,
        )

    def scan_due_plants(self, user_id: str, now: datetime | None = None) -> str:
        """Task: Scan all plants for a user and return a grouped watering reminder message.
        Input: The user id and an optional current datetime override.
        Output: A friendly reminder response for due plants.
        Failures: File IO and parsing issues can raise runtime exceptions.
        """

        self.file_manager.ensure_workspace()
        timestamp = iso_now(now)
        plants = [row for row in self.file_manager.read_csv(self.file_manager.plants_csv_path) if row["user_id"] == user_id]
        due_payloads: list[dict[str, Any]] = []
        for plant in plants:
            context = self.context_builder.build(user_id=user_id, plant_id=plant["id"])
            analysis = self.time_series_analyzer.analyze(events=context["all_plant_events"], now_timestamp=timestamp)
            watering_schedule = self.watering_scheduler.compute(context=context, analysis=analysis)
            if watering_schedule["reminder_due"]:
                due_payloads.append(
                    {
                        "plant": plant,
                        "context": context,
                        "analysis": analysis,
                        "schedule": watering_schedule,
                    }
                )

        return self.reminder_agent.generate(due_plants=due_payloads, now_timestamp=timestamp)

    def _log_raw_message(self, user_id: str, message: str, timestamp: str) -> None:
        """Task: Append the raw user message to the plain-text audit log.
        Input: The user id, message text, and timestamp string.
        Output: The raw log file updated on disk.
        Failures: Raises OSError if the log file cannot be written.
        """

        self.file_manager.append_text(
            self.file_manager.raw_log_path(user_id),
            f"{timestamp} | {message}\n",
        )

    def _persist_plant(self, plant: dict[str, str]) -> None:
        """Task: Upsert a plant row in the plants CSV file.
        Input: The plant row dictionary to persist.
        Output: The plants CSV rewritten with the latest plant state.
        Failures: Raises OSError if the plants CSV cannot be written.
        """

        plants = self.file_manager.read_csv(self.file_manager.plants_csv_path)
        updated_plants = [plant if row["id"] == plant["id"] else row for row in plants]
        if not any(row["id"] == plant["id"] for row in plants):
            updated_plants.append(plant)
        self.file_manager.write_csv(self.file_manager.plants_csv_path, updated_plants, PLANT_HEADERS)

    def _persist_events(
        self,
        plant_id: str,
        extraction: dict[str, list[dict[str, Any]]],
        timestamp: str,
    ) -> None:
        """Task: Append deterministic event rows produced by the extractor.
        Input: The plant id, extraction payload, and current timestamp.
        Output: Matching events appended to the events CSV file.
        Failures: Raises OSError if the events CSV cannot be written.
        """

        for event in extraction["time_series_events"]:
            self.file_manager.append_csv(
                self.file_manager.events_csv_path,
                {
                    "event_id": make_id("event"),
                    "plant_id": plant_id,
                    "event_type": event["event_type"],
                    "subtype": event.get("subtype", ""),
                    "value": event.get("value", ""),
                    "metadata": json.dumps(event.get("metadata", {}), sort_keys=True),
                    "timestamp": event.get("timestamp", timestamp),
                    "source": "cli",
                },
                EVENT_HEADERS,
            )

    def _persist_rooms(self, rooms: list[dict[str, str]]) -> None:
        """Task: Persist the complete room list to the rooms CSV file.
        Input: The room row dictionaries to write.
        Output: The rooms CSV rewritten on disk.
        Failures: Raises OSError if the rooms CSV cannot be written.
        """

        self.file_manager.write_csv(self.file_manager.rooms_csv_path, rooms, ROOM_HEADERS)

    def _apply_room_facts(
        self,
        user_id: str,
        plant: dict[str, str],
        room_facts: list[dict[str, str]],
    ) -> dict[str, str]:
        """Task: Upsert room rows and assign the latest detected room to the current plant.
        Input: The user id, current plant row, and room fact dictionaries from extraction.
        Output: The updated plant row, potentially with a new room_id.
        Failures: Raises OSError if the rooms CSV cannot be written.
        """

        if not room_facts:
            return plant

        rooms = self.file_manager.read_csv(self.file_manager.rooms_csv_path)
        latest_room_fact = room_facts[-1]
        room_name = latest_room_fact.get("name", "General Room")
        room_type = latest_room_fact.get("type", "")
        window_direction = latest_room_fact.get("window_direction", "")

        existing_room = next(
            (
                room
                for room in rooms
                if room["user_id"] == user_id and room["name"].lower() == room_name.lower()
            ),
            None,
        )

        if existing_room is None:
            existing_room = {
                "id": make_id("room"),
                "user_id": user_id,
                "name": room_name,
                "type": room_type,
                "window_direction": window_direction,
                "size_sqft": "",
                "has_grow_light": "false",
                "city": "",
            }
            rooms.append(existing_room)
        else:
            existing_room["type"] = room_type or existing_room["type"]
            existing_room["window_direction"] = window_direction or existing_room["window_direction"]

        self.file_manager.write_csv(self.file_manager.rooms_csv_path, rooms, ROOM_HEADERS)
        plant["room_id"] = existing_room["id"]
        return plant

    def _write_memory(self, user_id: str, payload: dict[str, Any]) -> None:
        """Task: Persist per-user JSON memory such as the last used plant id.
        Input: The user id and memory payload dictionary.
        Output: The per-user memory JSON file written to disk.
        Failures: Raises OSError if the memory file cannot be written.
        """

        self.file_manager.write_json(self.file_manager.user_memory_path(user_id), payload)

    def _summarize_recent_activity(self, events: list[dict[str, str]]) -> str:
        """Task: Generate a short deterministic summary of the latest plant activity.
        Input: A list of recent event rows for the plant.
        Output: A short activity summary sentence fragment.
        Failures: No failure is expected.
        """

        if not events:
            return "I have no recorded activity for this plant yet."

        latest_event = events[-1]
        event_type = latest_event["event_type"]
        subtype = latest_event.get("subtype", "")
        timestamp = latest_event["timestamp"]

        if event_type == "issue" and subtype:
            return f"The latest recorded issue was {subtype.replace('_', ' ')} on {timestamp}."

        return f"The latest recorded activity was {event_type} on {timestamp}."

    def _is_reminder_query(self, message: str) -> bool:
        """Task: Determine whether a message is asking for watering reminders or due plants.
        Input: The raw user message text.
        Output: True when the message should trigger the reminder scan, otherwise False.
        Failures: No failure is expected.
        """

        lowered = message.lower()
        reminder_cues = ("remind", "due", "need water", "watering schedule", "which plants")
        return any(cue in lowered for cue in reminder_cues)


def build_default_orchestrator(base_dir: Path | None = None) -> Orchestrator:
    """Task: Build the default deterministic backend with relative file storage.
    Input: An optional base directory override, mainly for tests.
    Output: A fully wired Orchestrator instance.
    Failures: No failure is expected unless invalid constructor arguments are supplied.
    """

    script_dir = base_dir or Path(__file__).resolve().parent
    file_manager = FileManager(script_dir)
    return Orchestrator(
        file_manager=file_manager,
        plant_resolver=PlantResolver(),
        memory_extractor=MemoryExtractor(),
        conversation_agent=ConversationAgent(),
        context_builder=ContextBuilder(file_manager),
        time_series_analyzer=TimeSeriesAnalyzer(),
        watering_scheduler=WateringScheduler(),
        decision_engine=DecisionEngine(),
        reminder_agent=ReminderAgent(),
        response_generator=ResponseGenerator(),
    )
