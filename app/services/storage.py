"""CSV storage helpers for per-user Gemini API keys."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


CSV_HEADERS = ["user_id", "gemini_api_key", "datetime"]


@dataclass
class KeyRecord:
    """Task: Represent a single Gemini API key record stored in CSV.
    Input: A user id, Gemini API key, and ISO8601 timestamp.
    Output: A simple in-memory data object used by the storage layer.
    Failures: Incorrect field values can lead to later lookup or validation errors.
    """

    user_id: int
    gemini_api_key: str
    saved_at: str


class UserKeyStore:
    """Task: Persist and retrieve per-user Gemini API keys using a CSV file.
    Input: A file path pointing to the CSV store on disk.
    Output: Read and write methods for user Gemini API key records.
    Failures: File permission issues or malformed CSV rows may interrupt read/write operations.
    """

    def __init__(self, csv_path: Path) -> None:
        """Task: Initialize the CSV-backed user key store.
        Input: The filesystem path to the CSV file.
        Output: A ready-to-use UserKeyStore instance.
        Failures: Does not create directories immediately; later calls can fail if the path is unwritable.
        """

        self.csv_path = csv_path

    def ensure_store_exists(self) -> None:
        """Task: Create the CSV file and headers when the store does not yet exist.
        Input: No direct arguments; uses the configured CSV file path.
        Output: A CSV file on disk with the expected header row.
        Failures: Raises OSError when the directory or file cannot be created.
        """

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if self.csv_path.exists():
            return
        with self.csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(CSV_HEADERS)

    def append_key(self, user_id: int, gemini_api_key: str) -> KeyRecord:
        """Task: Save a newly submitted Gemini API key for a Telegram user.
        Input: The user's numeric Telegram id and the submitted Gemini API key.
        Output: The created KeyRecord, including the persisted timestamp.
        Failures: Raises OSError on file write failures.
        """

        record = KeyRecord(
            user_id=user_id,
            gemini_api_key=gemini_api_key,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
        with self.csv_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([record.user_id, record.gemini_api_key, record.saved_at])
        return record

    def fetch_latest_key(self, user_id: int) -> Optional[KeyRecord]:
        """Task: Retrieve the most recently saved Gemini API key for a user.
        Input: The user's numeric Telegram id.
        Output: The latest KeyRecord for that user, or None if no key exists.
        Failures: Raises OSError for unreadable files or ValueError for malformed user ids in CSV rows.
        """

        records = [record for record in self._read_all_records() if record.user_id == user_id]
        if not records:
            return None
        return max(records, key=lambda item: item.saved_at)

    def remove_record(self, target_record: KeyRecord) -> None:
        """Task: Remove a specific CSV row, typically after a failed Gemini key validation.
        Input: The exact KeyRecord to remove from the store.
        Output: The CSV file rewritten without the target record.
        Failures: Raises OSError for read/write issues while rewriting the file.
        """

        retained_records = [
            record
            for record in self._read_all_records()
            if not (
                record.user_id == target_record.user_id
                and record.gemini_api_key == target_record.gemini_api_key
                and record.saved_at == target_record.saved_at
            )
        ]
        with self.csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(CSV_HEADERS)
            for record in retained_records:
                writer.writerow([record.user_id, record.gemini_api_key, record.saved_at])

    def remove_api_key(self, user_id: int) -> None:
        """Task: Remove all Gemini API key records for a specific user from the CSV store.
        Input: The numeric Telegram user id.
        Output: The CSV file rewritten without the user's records.
        Failures: Raises OSError for read/write issues while rewriting the file.
        """

        retained_records = [
            record
            for record in self._read_all_records()
            if record.user_id != user_id
        ]
        with self.csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(CSV_HEADERS)
            for record in retained_records:
                writer.writerow([record.user_id, record.gemini_api_key, record.saved_at])

    def _read_all_records(self) -> List[KeyRecord]:
        """Task: Load all Gemini API key records from the CSV store.
        Input: No direct arguments; reads the configured CSV file.
        Output: A list of KeyRecord instances in file order.
        Failures: Raises OSError if the CSV file cannot be read or ValueError if row data is malformed.
        """

        self.ensure_store_exists()
        records: List[KeyRecord] = []
        with self.csv_path.open("r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                if not row.get("user_id") or not row.get("gemini_api_key") or not row.get("datetime"):
                    continue
                records.append(
                    KeyRecord(
                        user_id=int(row["user_id"]),
                        gemini_api_key=row["gemini_api_key"],
                        saved_at=row["datetime"],
                    )
                )
        return records

