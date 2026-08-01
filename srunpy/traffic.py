"""Active-interface traffic sampling and minute aggregation."""

import math
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import psutil

from srunpy.traffic_store import (
    MinuteTrafficRecord,
    TrafficHistoryStore,
    anonymize_interface_id,
)


@dataclass(frozen=True)
class TrafficCounterSample:
    interface_name: str
    interface_ip: str
    received_bytes: int
    sent_bytes: int
    monotonic_time: float
    timestamp: float


class CounterProvider(Protocol):
    def sample(
        self,
        preferred_ip: Optional[str],
        gateway_ip: str,
    ) -> Optional[TrafficCounterSample]: ...


class TrafficCounterProvider:
    """Read psutil counters for the adapter owning the selected source IP."""

    def __init__(
        self,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock

    @staticmethod
    def discover_route_source_ip(gateway_ip: str) -> Optional[str]:
        if not gateway_ip:
            return None
        route_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            route_socket.connect((gateway_ip, 9))
            return str(route_socket.getsockname()[0])
        except OSError:
            return None
        finally:
            route_socket.close()

    @staticmethod
    def map_ip_to_interface(
        interface_ip: str,
        interface_addresses: dict[str, list[Any]],
    ) -> Optional[str]:
        for interface_name, addresses in interface_addresses.items():
            if any(
                getattr(address, "family", None) == socket.AF_INET
                and getattr(address, "address", None) == interface_ip
                for address in addresses
            ):
                return interface_name
        return None

    def sample(
        self,
        preferred_ip: Optional[str],
        gateway_ip: str,
    ) -> Optional[TrafficCounterSample]:
        interface_ip = preferred_ip or self.discover_route_source_ip(gateway_ip)
        if not interface_ip:
            return None
        interface_name = self.map_ip_to_interface(interface_ip, psutil.net_if_addrs())
        if interface_name is None:
            return None
        counters = psutil.net_io_counters(pernic=True, nowrap=True).get(interface_name)
        if counters is None:
            return None
        return TrafficCounterSample(
            interface_name=interface_name,
            interface_ip=interface_ip,
            received_bytes=int(counters.bytes_recv),
            sent_bytes=int(counters.bytes_sent),
            monotonic_time=self._monotonic_clock(),
            timestamp=self._wall_clock(),
        )


@dataclass
class _MinuteAccumulator:
    minute_utc: int
    interface_name: str
    received_bytes: int = 0
    sent_bytes: int = 0
    download_rate_sum: float = 0.0
    upload_rate_sum: float = 0.0
    peak_download_rate: float = 0.0
    peak_upload_rate: float = 0.0
    sample_count: int = 0
    gap_count: int = 0

    def add_valid_sample(
        self,
        received_bytes: int,
        sent_bytes: int,
        download_rate: float,
        upload_rate: float,
    ) -> None:
        self.received_bytes += received_bytes
        self.sent_bytes += sent_bytes
        self.download_rate_sum += download_rate
        self.upload_rate_sum += upload_rate
        self.peak_download_rate = max(self.peak_download_rate, download_rate)
        self.peak_upload_rate = max(self.peak_upload_rate, upload_rate)
        self.sample_count += 1

    def to_record(self) -> MinuteTrafficRecord:
        sample_divisor = self.sample_count or 1
        return MinuteTrafficRecord(
            minute_utc=self.minute_utc,
            interface_id=anonymize_interface_id(self.interface_name),
            interface_name=self.interface_name,
            received_bytes=self.received_bytes,
            sent_bytes=self.sent_bytes,
            average_download_bytes_per_second=self.download_rate_sum / sample_divisor,
            average_upload_bytes_per_second=self.upload_rate_sum / sample_divisor,
            peak_download_bytes_per_second=self.peak_download_rate,
            peak_upload_bytes_per_second=self.peak_upload_rate,
            sample_count=self.sample_count,
            gap_count=self.gap_count,
        )


class TrafficMonitorService:
    """Sample traffic in the background while serving lock-protected snapshots."""

    EMA_TIME_CONSTANT_SECONDS = 3.0

    def __init__(
        self,
        provider: CounterProvider,
        history_store: TrafficHistoryStore,
        *,
        preferred_ip: Optional[str],
        gateway_ip: str,
        sample_interval: float = 1.0,
        history_enabled: bool = True,
        retention_days: int = 7,
    ) -> None:
        self.provider = provider
        self.history_store = history_store
        self.preferred_ip = preferred_ip
        self.gateway_ip = gateway_ip
        self.sample_interval = max(0.5, float(sample_interval))
        self.history_enabled = bool(history_enabled)
        self.retention_days = min(max(int(retention_days), 1), 30)
        self._maximum_sample_gap = max(10.0, self.sample_interval * 5.0)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._restart_after_stop = False
        self._baseline: Optional[TrafficCounterSample] = None
        self._accumulator: Optional[_MinuteAccumulator] = None
        self._current_interface_id: Optional[str] = None
        self._recent_samples: deque[dict[str, Any]] = deque(maxlen=60)
        self._started_at: Optional[float] = None
        self._last_cleanup_time: float = 0.0
        self._snapshot = self._empty_snapshot("正在建立采样基线")

    @staticmethod
    def _empty_snapshot(message: str) -> dict[str, Any]:
        return {
            "available": False,
            "gap": True,
            "message": message,
            "interface_name": None,
            "interface_ip": None,
            "timestamp": None,
            "download_bytes_per_second": None,
            "upload_bytes_per_second": None,
            "raw_download_bytes_per_second": None,
            "raw_upload_bytes_per_second": None,
            "peak_download_bytes_per_second": 0.0,
            "peak_upload_bytes_per_second": 0.0,
            "monitoring_duration_seconds": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        if self.history_enabled:
            self.history_store.cleanup(self.retention_days)
            # The explicit cleanup above counts as the periodic one, so the
            # worker does not purge again on its very first iteration.
            self._last_cleanup_time = time.monotonic()
        self._stop_event.clear()
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            name="SRunPy-TrafficMonitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> bool:
        """Wake and stop the worker without racing a still-running sample.

        Return ``True`` only after the worker thread has been observed to exit.
        A sampler can be blocked inside the provider, so callers must not
        replace this service when the bounded join times out.
        """
        with self._lock:
            self._restart_after_stop = False
            self._stop_event.set()
        worker_thread = self._thread
        if worker_thread is not None and worker_thread is not threading.current_thread():
            worker_thread.join(timeout=max(2.0, self.sample_interval * 2.0))
        with self._lock:
            worker_stopped = worker_thread is None or not worker_thread.is_alive()
            if worker_stopped:
                self._flush_accumulator()
                if worker_thread is not None:
                    self._thread = None
        return worker_stopped

    def resume_after_stop(self) -> None:
        """Resume sampling after a timed-out stop if the old worker is alive.

        A settings transaction can fail while a provider call is blocked. The
        rollback reuses the old monitor, so remember the start request and
        launch a fresh worker only after the blocked worker has exited.
        """
        with self._lock:
            worker_thread = self._thread
            if worker_thread is not None and worker_thread.is_alive():
                if self._stop_event.is_set():
                    self._restart_after_stop = True
                return
        self.start()

    def update_selection(self, preferred_ip: Optional[str], gateway_ip: str) -> None:
        with self._lock:
            if preferred_ip == self.preferred_ip and gateway_ip == self.gateway_ip:
                return
            self.preferred_ip = preferred_ip
            self.gateway_ip = gateway_ip
            self._baseline = None
            self._record_gap(None, "活动网卡已切换，正在重建基线")

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                iteration_started_at = time.monotonic()
                self.sample_once()
                self._maybe_cleanup()
                elapsed_time = time.monotonic() - iteration_started_at
                self._stop_event.wait(max(0.0, self.sample_interval - elapsed_time))
        finally:
            restart_thread: Optional[threading.Thread] = None
            with self._lock:
                if (
                    self._restart_after_stop
                    and self._thread is threading.current_thread()
                ):
                    self._restart_after_stop = False
                    self._stop_event.clear()
                    self._started_at = time.monotonic()
                    restart_thread = threading.Thread(
                        target=self._run,
                        name="SRunPy-TrafficMonitor",
                        daemon=True,
                    )
                    self._thread = restart_thread
            if restart_thread is not None:
                restart_thread.start()

    def _maybe_cleanup(self) -> None:
        """Periodically purge expired history rows beyond just monitor startup."""
        now = time.monotonic()
        if not self.history_enabled:
            self._last_cleanup_time = now
            return
        if now - self._last_cleanup_time < 3600.0:
            return
        try:
            self.history_store.cleanup(self.retention_days)
        except Exception:
            # Retention cleanup must never bring the sampling loop down.
            pass
        finally:
            self._last_cleanup_time = now

    def sample_once(self) -> dict[str, Any]:
        try:
            sample = self.provider.sample(self.preferred_ip, self.gateway_ip)
        except Exception:
            sample = None
        with self._lock:
            if sample is None:
                self._baseline = None
                self._record_gap(None, "未找到活动网卡计数器")
                return dict(self._snapshot)

            self._current_interface_id = anonymize_interface_id(sample.interface_name)
            self._rotate_minute_if_needed(sample)
            baseline = self._baseline
            self._baseline = sample
            if baseline is None:
                self._record_gap(sample, "正在建立采样基线")
                return dict(self._snapshot)

            elapsed_seconds = sample.monotonic_time - baseline.monotonic_time
            interface_changed = (
                sample.interface_name != baseline.interface_name
                or sample.interface_ip != baseline.interface_ip
            )
            counters_receded = (
                sample.received_bytes < baseline.received_bytes
                or sample.sent_bytes < baseline.sent_bytes
            )
            invalid_elapsed_time = (
                elapsed_seconds <= 0 or elapsed_seconds > self._maximum_sample_gap
            )
            if interface_changed or counters_receded or invalid_elapsed_time:
                self._record_gap(sample, "采样中断，已重建计数器基线")
                return dict(self._snapshot)

            received_delta = sample.received_bytes - baseline.received_bytes
            sent_delta = sample.sent_bytes - baseline.sent_bytes
            raw_download_rate = received_delta / elapsed_seconds
            raw_upload_rate = sent_delta / elapsed_seconds
            previous_download_rate = self._snapshot.get("download_bytes_per_second")
            previous_upload_rate = self._snapshot.get("upload_bytes_per_second")
            smoothing_factor = 1.0 - math.exp(
                -elapsed_seconds / self.EMA_TIME_CONSTANT_SECONDS
            )
            smoothed_download_rate = self._smooth_rate(
                raw_download_rate,
                previous_download_rate,
                smoothing_factor,
            )
            smoothed_upload_rate = self._smooth_rate(
                raw_upload_rate,
                previous_upload_rate,
                smoothing_factor,
            )
            peak_download_rate = max(
                float(self._snapshot.get("peak_download_bytes_per_second") or 0.0),
                raw_download_rate,
            )
            peak_upload_rate = max(
                float(self._snapshot.get("peak_upload_bytes_per_second") or 0.0),
                raw_upload_rate,
            )
            self._snapshot = {
                "available": True,
                "gap": False,
                "message": None,
                "interface_name": sample.interface_name,
                "interface_ip": sample.interface_ip,
                "timestamp": sample.timestamp,
                "download_bytes_per_second": smoothed_download_rate,
                "upload_bytes_per_second": smoothed_upload_rate,
                "raw_download_bytes_per_second": raw_download_rate,
                "raw_upload_bytes_per_second": raw_upload_rate,
                "peak_download_bytes_per_second": peak_download_rate,
                "peak_upload_bytes_per_second": peak_upload_rate,
                "monitoring_duration_seconds": self._monitoring_duration(),
            }
            self._recent_samples.append(self._point_from_snapshot())
            if self._accumulator is not None:
                self._accumulator.add_valid_sample(
                    received_delta,
                    sent_delta,
                    raw_download_rate,
                    raw_upload_rate,
                )
            return dict(self._snapshot)

    @staticmethod
    def _smooth_rate(raw_rate: float, previous_rate: Any, smoothing_factor: float) -> float:
        if previous_rate is None:
            return raw_rate
        return float(previous_rate) + smoothing_factor * (raw_rate - float(previous_rate))

    def _monitoring_duration(self) -> int:
        if self._started_at is None:
            return 0
        return max(0, int(time.monotonic() - self._started_at))

    def _record_gap(
        self,
        sample: Optional[TrafficCounterSample],
        message: str,
    ) -> None:
        if sample is not None:
            self._rotate_minute_if_needed(sample)
        if self._accumulator is not None:
            self._accumulator.gap_count += 1
        previous_snapshot = self._snapshot
        self._snapshot = {
            **self._empty_snapshot(message),
            "interface_name": sample.interface_name if sample else previous_snapshot.get("interface_name"),
            "interface_ip": sample.interface_ip if sample else previous_snapshot.get("interface_ip"),
            "timestamp": sample.timestamp if sample else time.time(),
            "peak_download_bytes_per_second": previous_snapshot.get(
                "peak_download_bytes_per_second", 0.0
            ),
            "peak_upload_bytes_per_second": previous_snapshot.get(
                "peak_upload_bytes_per_second", 0.0
            ),
            "monitoring_duration_seconds": self._monitoring_duration(),
        }
        self._recent_samples.append(self._point_from_snapshot())

    def _point_from_snapshot(self) -> dict[str, Any]:
        return {
            "timestamp": self._snapshot.get("timestamp"),
            "download_bytes_per_second": self._snapshot.get("raw_download_bytes_per_second"),
            "upload_bytes_per_second": self._snapshot.get("raw_upload_bytes_per_second"),
            "gap": bool(self._snapshot.get("gap")),
        }

    def _rotate_minute_if_needed(self, sample: TrafficCounterSample) -> None:
        sample_minute = int(sample.timestamp) // 60 * 60
        if self._accumulator is None:
            self._accumulator = _MinuteAccumulator(sample_minute, sample.interface_name)
            return
        if (
            sample_minute != self._accumulator.minute_utc
            or sample.interface_name != self._accumulator.interface_name
        ):
            self._flush_accumulator()
            self._accumulator = _MinuteAccumulator(sample_minute, sample.interface_name)

    def _flush_accumulator(self) -> None:
        if self._accumulator is None:
            return
        if self.history_enabled:
            self.history_store.write_minute(self._accumulator.to_record())
        self._accumulator = None

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "supported": True,
            "source": "windows_active_interface",
            "sample_interval_seconds": self.sample_interval,
            "history_enabled": self.history_enabled,
            "retention_days": self.retention_days,
            "ranges": ["recent", "1h", "5h", "12h", "24h", "7d"],
        }

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._snapshot)
            snapshot["monitoring_duration_seconds"] = self._monitoring_duration()
            return snapshot

    def get_history(self, history_range: str) -> list[dict[str, Any]]:
        if history_range == "recent":
            with self._lock:
                return [dict(point) for point in self._recent_samples]
        if not self.history_enabled:
            return []
        # Persisted history is scoped to the interface currently being monitored so
        # that a multi-NIC machine never blends unrelated adapters into one series.
        with self._lock:
            current_interface_id = self._current_interface_id
        if current_interface_id is None:
            return []
        return self.history_store.get_history(
            history_range, interface_id=current_interface_id
        )

    def clear_history(self) -> None:
        with self._lock:
            self.history_store.clear()
            self._recent_samples.clear()
