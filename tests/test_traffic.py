import socket
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from srunpy.traffic import (
    TrafficCounterProvider,
    TrafficCounterSample,
    TrafficMonitorService,
)
from srunpy.traffic_store import MinuteTrafficRecord, TrafficHistoryStore


class SequenceCounterProvider:
    def __init__(self, samples: list[Optional[TrafficCounterSample]]) -> None:
        self.samples = deque(samples)

    def sample(
        self,
        preferred_ip: Optional[str],
        gateway_ip: str,
    ) -> Optional[TrafficCounterSample]:
        return self.samples.popleft()


def create_sample(
    received_bytes: int,
    sent_bytes: int,
    monotonic_time: float,
    timestamp: float,
    *,
    interface_name: str = "Wi-Fi",
    interface_ip: str = "10.0.0.2",
) -> TrafficCounterSample:
    return TrafficCounterSample(
        interface_name=interface_name,
        interface_ip=interface_ip,
        received_bytes=received_bytes,
        sent_bytes=sent_bytes,
        monotonic_time=monotonic_time,
        timestamp=timestamp,
    )


def create_monitor(tmp_path: Path, samples: list[Optional[TrafficCounterSample]]) -> TrafficMonitorService:
    return TrafficMonitorService(
        SequenceCounterProvider(samples),
        TrafficHistoryStore(tmp_path / "traffic.db"),
        preferred_ip="10.0.0.2",
        gateway_ip="10.0.0.1",
    )


def test_maps_ipv4_address_to_interface_without_duplicate_adapter_samples() -> None:
    addresses = {
        "Wi-Fi": [
            SimpleNamespace(family=socket.AF_INET, address="10.0.0.2"),
            SimpleNamespace(family=socket.AF_INET, address="10.0.0.3"),
        ],
        "Ethernet": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.2")],
    }

    assert TrafficCounterProvider.map_ip_to_interface("10.0.0.3", addresses) == "Wi-Fi"
    assert TrafficCounterProvider.map_ip_to_interface("172.16.0.2", addresses) is None


def test_first_sample_is_gap_then_counter_delta_produces_raw_rates(tmp_path: Path) -> None:
    monitor = create_monitor(
        tmp_path,
        [create_sample(1000, 500, 10.0, 120.0), create_sample(3000, 1500, 12.0, 122.0)],
    )

    first_snapshot = monitor.sample_once()
    second_snapshot = monitor.sample_once()

    assert first_snapshot["gap"] is True
    assert second_snapshot["gap"] is False
    assert second_snapshot["raw_download_bytes_per_second"] == 1000
    assert second_snapshot["raw_upload_bytes_per_second"] == 500


@pytest.mark.parametrize(
    ("second_sample", "expected_message"),
    [
        (create_sample(500, 200, 11.0, 121.0), "采样中断"),
        (create_sample(2000, 1000, 30.0, 140.0), "采样中断"),
        (
            create_sample(2000, 1000, 11.0, 121.0, interface_name="Ethernet"),
            "采样中断",
        ),
    ],
)
def test_reset_sleep_gap_and_interface_change_rebuild_baseline(
    tmp_path: Path,
    second_sample: TrafficCounterSample,
    expected_message: str,
) -> None:
    monitor = create_monitor(tmp_path, [create_sample(1000, 500, 10.0, 120.0), second_sample])

    monitor.sample_once()
    snapshot = monitor.sample_once()

    assert snapshot["gap"] is True
    assert expected_message in snapshot["message"]


def test_ema_smooths_a_following_rate_change(tmp_path: Path) -> None:
    monitor = create_monitor(
        tmp_path,
        [
            create_sample(0, 0, 1.0, 120.0),
            create_sample(300, 300, 2.0, 121.0),
            create_sample(3300, 3300, 3.0, 122.0),
        ],
    )

    monitor.sample_once()
    first_rate = monitor.sample_once()["download_bytes_per_second"]
    smoothed_rate = monitor.sample_once()["download_bytes_per_second"]

    assert first_rate == 300
    assert 300 < smoothed_rate < 3000


def create_record(minute_utc: int, *, sample_count: int = 1) -> MinuteTrafficRecord:
    return MinuteTrafficRecord(
        minute_utc=minute_utc,
        interface_id="anonymous",
        interface_name="Wi-Fi",
        received_bytes=600,
        sent_bytes=300,
        average_download_bytes_per_second=10.0,
        average_upload_bytes_per_second=5.0,
        peak_download_bytes_per_second=20.0,
        peak_upload_bytes_per_second=10.0,
        sample_count=sample_count,
        gap_count=0,
    )


def test_history_retention_range_limit_and_clear(tmp_path: Path) -> None:
    store = TrafficHistoryStore(tmp_path / "traffic.db")
    current_time = 10 * 24 * 60 * 60
    old_minute = int(current_time - 8 * 24 * 60 * 60) // 60 * 60
    recent_minutes = [int(current_time - offset * 60) // 60 * 60 for offset in range(5)]
    store.write_many([create_record(old_minute), *(create_record(value) for value in recent_minutes)])

    deleted_count = store.cleanup(7, current_time=current_time)
    history = store.get_history("24h", maximum_points=2, current_time=current_time)

    assert deleted_count == 1
    assert len(history) <= 2
    assert all(point["download_bytes_per_second"] == 10.0 for point in history)
    store.clear()
    assert store.get_history("7d", current_time=current_time) == []


def test_stop_does_not_restart_worker_while_sample_is_blocked(tmp_path: Path) -> None:
    class BlockingProvider:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()

        def sample(
            self,
            preferred_ip: Optional[str],
            gateway_ip: str,
        ) -> Optional[TrafficCounterSample]:
            self.entered.set()
            self.release.wait(timeout=5)
            return None

    provider = BlockingProvider()
    monitor = TrafficMonitorService(
        provider,
        TrafficHistoryStore(tmp_path / "traffic.db"),
        preferred_ip="10.0.0.2",
        gateway_ip="10.0.0.1",
    )

    monitor.start()
    assert provider.entered.wait(timeout=2)
    worker_before_stop = monitor._thread

    monitor.stop()
    assert monitor.is_running

    monitor.start()
    assert monitor._thread is worker_before_stop

    provider.release.set()
    deadline = time.monotonic() + 3
    while monitor.is_running and time.monotonic() < deadline:
        time.sleep(0.05)

    monitor.stop()
    assert monitor.is_running is False


@pytest.mark.parametrize(
    ("history_range", "range_hours"),
    [("1h", 1), ("5h", 5), ("12h", 12), ("24h", 24)],
)
def test_hour_history_ranges_apply_their_own_cutoffs(
    tmp_path: Path,
    history_range: str,
    range_hours: int,
) -> None:
    store = TrafficHistoryStore(tmp_path / f"traffic-{history_range}.db")
    current_time = 10 * 24 * 60 * 60
    inside_range_minute = int(current_time - range_hours * 60 * 60 + 60) // 60 * 60
    outside_range_minute = int(current_time - range_hours * 60 * 60 - 60) // 60 * 60
    store.write_many(
        [create_record(outside_range_minute), create_record(inside_range_minute)]
    )

    history = store.get_history(history_range, current_time=current_time)

    assert [point["timestamp"] for point in history] == [inside_range_minute]


def test_minute_rotation_persists_raw_average_and_peak(tmp_path: Path) -> None:
    monitor = create_monitor(
        tmp_path,
        [
            create_sample(0, 0, 1.0, 120.0),
            create_sample(600, 300, 2.0, 121.0),
            create_sample(1800, 900, 3.0, 180.0),
        ],
    )

    monitor.sample_once()
    monitor.sample_once()
    monitor.sample_once()
    history = monitor.history_store.get_history("24h", current_time=181.0)

    assert history[0]["received_bytes"] == 600
    assert history[0]["download_bytes_per_second"] == 600
    assert history[0]["peak_download_bytes_per_second"] == 600
