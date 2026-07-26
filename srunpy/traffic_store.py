"""SQLite persistence for minute-level local network traffic aggregates."""

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


def get_default_traffic_database_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "SRunPy" / "traffic.db"


def anonymize_interface_id(interface_name: str) -> str:
    return hashlib.sha256(interface_name.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class MinuteTrafficRecord:
    minute_utc: int
    interface_id: str
    interface_name: str
    received_bytes: int
    sent_bytes: int
    average_download_bytes_per_second: float
    average_upload_bytes_per_second: float
    peak_download_bytes_per_second: float
    peak_upload_bytes_per_second: float
    sample_count: int
    gap_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrafficHistoryStore:
    """Thread-safe store with bounded retention and fixed-range queries."""

    _RANGE_SECONDS = {
        "1h": 60 * 60,
        "5h": 5 * 60 * 60,
        "12h": 12 * 60 * 60,
        "24h": 24 * 60 * 60,
        "7d": 7 * 24 * 60 * 60,
    }

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS traffic_minutes (
                    minute_utc INTEGER NOT NULL,
                    interface_id TEXT NOT NULL,
                    interface_name TEXT NOT NULL,
                    received_bytes INTEGER NOT NULL,
                    sent_bytes INTEGER NOT NULL,
                    average_download_bps REAL NOT NULL,
                    average_upload_bps REAL NOT NULL,
                    peak_download_bps REAL NOT NULL,
                    peak_upload_bps REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    gap_count INTEGER NOT NULL,
                    PRIMARY KEY (minute_utc, interface_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS traffic_minutes_time_idx "
                "ON traffic_minutes(minute_utc)"
            )

    def write_minute(self, record: MinuteTrafficRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO traffic_minutes (
                    minute_utc, interface_id, interface_name, received_bytes, sent_bytes,
                    average_download_bps, average_upload_bps, peak_download_bps,
                    peak_upload_bps, sample_count, gap_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(minute_utc, interface_id) DO UPDATE SET
                    interface_name = excluded.interface_name,
                    received_bytes = excluded.received_bytes,
                    sent_bytes = excluded.sent_bytes,
                    average_download_bps = excluded.average_download_bps,
                    average_upload_bps = excluded.average_upload_bps,
                    peak_download_bps = excluded.peak_download_bps,
                    peak_upload_bps = excluded.peak_upload_bps,
                    sample_count = excluded.sample_count,
                    gap_count = excluded.gap_count
                """,
                (
                    record.minute_utc,
                    record.interface_id,
                    record.interface_name,
                    record.received_bytes,
                    record.sent_bytes,
                    record.average_download_bytes_per_second,
                    record.average_upload_bytes_per_second,
                    record.peak_download_bytes_per_second,
                    record.peak_upload_bytes_per_second,
                    record.sample_count,
                    record.gap_count,
                ),
            )

    def cleanup(self, retention_days: int, *, current_time: Optional[float] = None) -> int:
        effective_time = time.time() if current_time is None else current_time
        cutoff_minute = int(effective_time - retention_days * 24 * 60 * 60) // 60 * 60
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM traffic_minutes WHERE minute_utc < ?",
                (cutoff_minute,),
            )
            return max(0, cursor.rowcount)

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM traffic_minutes")

    def get_history(
        self,
        history_range: str,
        *,
        maximum_points: int = 2016,
        current_time: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        if history_range not in self._RANGE_SECONDS:
            raise ValueError("不支持的历史范围")
        bounded_maximum_points = min(max(int(maximum_points), 1), 2016)
        effective_time = time.time() if current_time is None else current_time
        cutoff_minute = int(effective_time - self._RANGE_SECONDS[history_range]) // 60 * 60
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM traffic_minutes
                WHERE minute_utc >= ?
                ORDER BY minute_utc ASC
                """,
                (cutoff_minute,),
            ).fetchall()
        records = [dict(row) for row in rows]
        return self._downsample(records, bounded_maximum_points)

    @staticmethod
    def _downsample(
        records: list[dict[str, Any]],
        maximum_points: int,
    ) -> list[dict[str, Any]]:
        if len(records) <= maximum_points:
            return [TrafficHistoryStore._row_to_api(record) for record in records]

        bucket_size = (len(records) + maximum_points - 1) // maximum_points
        result: list[dict[str, Any]] = []
        for bucket_start in range(0, len(records), bucket_size):
            bucket = records[bucket_start:bucket_start + bucket_size]
            sample_count = sum(int(record["sample_count"]) for record in bucket)
            weighted_download = sum(
                float(record["average_download_bps"]) * int(record["sample_count"])
                for record in bucket
            )
            weighted_upload = sum(
                float(record["average_upload_bps"]) * int(record["sample_count"])
                for record in bucket
            )
            result.append(
                {
                    "timestamp": int(bucket[-1]["minute_utc"]),
                    "download_bytes_per_second": (
                        weighted_download / sample_count if sample_count else None
                    ),
                    "upload_bytes_per_second": (
                        weighted_upload / sample_count if sample_count else None
                    ),
                    "peak_download_bytes_per_second": max(
                        float(record["peak_download_bps"]) for record in bucket
                    ),
                    "peak_upload_bytes_per_second": max(
                        float(record["peak_upload_bps"]) for record in bucket
                    ),
                    "received_bytes": sum(int(record["received_bytes"]) for record in bucket),
                    "sent_bytes": sum(int(record["sent_bytes"]) for record in bucket),
                    "sample_count": sample_count,
                    "gap_count": sum(int(record["gap_count"]) for record in bucket),
                    "gap": sample_count == 0,
                }
            )
        return result

    @staticmethod
    def _row_to_api(record: dict[str, Any]) -> dict[str, Any]:
        sample_count = int(record["sample_count"])
        return {
            "timestamp": int(record["minute_utc"]),
            "download_bytes_per_second": (
                float(record["average_download_bps"]) if sample_count else None
            ),
            "upload_bytes_per_second": (
                float(record["average_upload_bps"]) if sample_count else None
            ),
            "peak_download_bytes_per_second": float(record["peak_download_bps"]),
            "peak_upload_bytes_per_second": float(record["peak_upload_bps"]),
            "received_bytes": int(record["received_bytes"]),
            "sent_bytes": int(record["sent_bytes"]),
            "sample_count": sample_count,
            "gap_count": int(record["gap_count"]),
            "gap": sample_count == 0,
        }

    def write_many(self, records: Iterable[MinuteTrafficRecord]) -> None:
        for record in records:
            self.write_minute(record)
