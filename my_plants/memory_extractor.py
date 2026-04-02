"""Strict rule-based extraction of structured memory from messages."""

from __future__ import annotations

from typing import Any


class MemoryExtractor:
    """Task: Convert natural-language messages into deterministic structured facts using keyword rules only.
    Input: A raw user message string.
    Output: A dictionary with plant facts, room facts, time-series events, patterns, and issues.
    Failures: No failure is expected; unmatched messages simply produce empty lists.
    """

    def extract(self, message: str, timestamp: str) -> dict[str, list[dict[str, Any]]]:
        """Task: Apply strict keyword rules to identify events, issues, and room facts.
        Input: The raw user message text and current timestamp string.
        Output: A structured extraction dictionary containing only deterministic matches.
        Failures: No failure is expected; unmatched content returns empty lists.
        """

        lowered_message = message.lower()
        payload = {
            "plant_facts": [],
            "room_facts": [],
            "time_series_events": [],
            "patterns": [],
            "issues": [],
        }

        if any(keyword in lowered_message for keyword in ("watered", "watering")):
            payload["time_series_events"].append(
                {
                    "event_type": "watering",
                    "subtype": "manual",
                    "value": "completed",
                    "metadata": {"matched_keywords": ["watered", "watering"]},
                    "timestamp": timestamp,
                }
            )

        if "fertilized" in lowered_message:
            payload["time_series_events"].append(
                {
                    "event_type": "fertilizing",
                    "subtype": "manual",
                    "value": "completed",
                    "metadata": {"matched_keywords": ["fertilized"]},
                    "timestamp": timestamp,
                }
            )

        if "yellow leaves" in lowered_message:
            issue = {
                "event_type": "issue",
                "subtype": "yellow_leaves",
                "value": "reported",
                "metadata": {"matched_keywords": ["yellow leaves"]},
                "timestamp": timestamp,
            }
            payload["issues"].append(issue)
            payload["time_series_events"].append(issue)

        if "brown tips" in lowered_message:
            issue = {
                "event_type": "issue",
                "subtype": "brown_tips",
                "value": "reported",
                "metadata": {"matched_keywords": ["brown tips"]},
                "timestamp": timestamp,
            }
            payload["issues"].append(issue)
            payload["time_series_events"].append(issue)

        if "balcony" in lowered_message:
            payload["room_facts"].append(
                {
                    "name": "Balcony",
                    "type": "balcony",
                }
            )

        if "indoors" in lowered_message:
            payload["room_facts"].append(
                {
                    "name": "Indoor Room",
                    "type": "indoor",
                }
            )

        for direction in ("north", "south", "east", "west"):
            if f"{direction} window" in lowered_message:
                payload["room_facts"].append(
                    {
                        "name": f"{direction.capitalize()} Window Room",
                        "type": "indoor",
                        "window_direction": direction,
                    }
                )
                break

        return payload

