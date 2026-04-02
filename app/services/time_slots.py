"""Storage and logic for user time slots and snooze mechanics."""

import csv
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

class TimeSlotStore:
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        self._ensure_exists()
        
    def _ensure_exists(self) -> None:
        if not self.csv_path.exists():
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            with self.csv_path.open("w", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["user_id", "start_hour", "end_hour", "snoozed_fertilize_until"])

    def _read_all(self) -> Dict[int, Dict[str, Any]]:
        self._ensure_exists()
        records = {}
        with self.csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    records[int(row["user_id"])] = {
                        "start_hour": int(row["start_hour"]),
                        "end_hour": int(row["end_hour"]),
                        "snoozed_fertilize_until": row.get("snoozed_fertilize_until", "")
                    }
                except ValueError:
                    continue
        return records

    def _write_all(self, records: Dict[int, Dict[str, Any]]) -> None:
        with self.csv_path.open("w", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "start_hour", "end_hour", "snoozed_fertilize_until"])
            for uid, data in records.items():
                writer.writerow([
                    uid,
                    data["start_hour"],
                    data["end_hour"],
                    data["snoozed_fertilize_until"]
                ])

    def get_time_slot(self, user_id: int) -> tuple[int, int]:
        records = self._read_all()
        if user_id in records:
            return records[user_id]["start_hour"], records[user_id]["end_hour"]
        return 17, 19

    def upsert_time_slot(self, user_id: int, start_hour: int, end_hour: int) -> None:
        records = self._read_all()
        if user_id not in records:
            records[user_id] = {"snoozed_fertilize_until": ""}
        records[user_id]["start_hour"] = start_hour
        records[user_id]["end_hour"] = end_hour
        self._write_all(records)

    def set_snoozed_fertilize_until(self, user_id: int, date_str: str) -> None:
        records = self._read_all()
        if user_id not in records:
            records[user_id] = {"start_hour": 17, "end_hour": 19}
        records[user_id]["snoozed_fertilize_until"] = date_str
        self._write_all(records)
        
    def get_snoozed_fertilize_until(self, user_id: int) -> str:
        records = self._read_all()
        if user_id in records:
            return records[user_id]["snoozed_fertilize_until"]
        return ""
