"""Time-series calculations for plant event history."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class TimeSeriesAnalyzer:
    """Task: Compute watering metrics from recent event history.
    Input: Recent plant events and the current timestamp.
    Output: Aggregate watering statistics for downstream rules.
    Failures: Malformed timestamps can raise ValueError during datetime parsing.
    """

    def analyze(self, events: list[dict[str, str]], now_timestamp: str) -> dict[str, Any]:
        """Task: Calculate average watering interval, recency, and frequent-watering flags.
        Input: A list of recent event rows and the current timestamp string.
        Output: A dictionary of watering-related metrics.
        Failures: Raises ValueError when event timestamps are not valid ISO 8601 strings.
        """

        now_value = datetime.fromisoformat(now_timestamp)
        watering_times = sorted(
            datetime.fromisoformat(event["timestamp"])
            for event in events
            if event["event_type"] == "watering"
        )

        if not watering_times:
            return {
                "avg_watering_interval_days": None,
                "avg_watering_interval_days_last5": None,
                "days_since_last_watered": None,
                "last_watering_timestamp": None,
                "frequent_watering": False,
            }

        days_since_last_watered = (now_value - watering_times[-1]).days
        if len(watering_times) < 2:
            return {
                "avg_watering_interval_days": None,
                "avg_watering_interval_days_last5": None,
                "days_since_last_watered": days_since_last_watered,
                "last_watering_timestamp": watering_times[-1].strftime("%Y-%m-%dT%H:%M:%S"),
                "frequent_watering": False,
            }

        intervals = [
            (watering_times[index] - watering_times[index - 1]).days
            for index in range(1, len(watering_times))
        ]
        avg_interval = round(sum(intervals) / len(intervals), 2)
        recent_watering_times = watering_times[-5:]
        last5_intervals = [
            (recent_watering_times[index] - recent_watering_times[index - 1]).days
            for index in range(1, len(recent_watering_times))
        ]
        avg_interval_last5 = round(sum(last5_intervals) / len(last5_intervals), 2) if last5_intervals else None

        return {
            "avg_watering_interval_days": avg_interval,
            "avg_watering_interval_days_last5": avg_interval_last5,
            "days_since_last_watered": days_since_last_watered,
            "last_watering_timestamp": watering_times[-1].strftime("%Y-%m-%dT%H:%M:%S"),
            "frequent_watering": any(interval < 2 for interval in intervals),
        }
