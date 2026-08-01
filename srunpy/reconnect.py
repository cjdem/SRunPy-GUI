"""Cancelable automatic reconnection service with bounded per-interface backoff."""

import threading
import time
from collections.abc import Callable, Mapping
from typing import Hashable, Optional, Protocol


class ConnectionClient(Protocol):
    """Minimum gateway client behavior required by the reconnect service."""

    def is_connected(self) -> tuple[bool, bool, object]:
        """Return gateway availability, online state, and optional details."""


class ReconnectService:
    """Monitor configured interfaces and reconnect offline ones in the background."""

    def __init__(
        self,
        clients_provider: Callable[[], Mapping[Hashable, ConnectionClient]],
        login_callback: Callable[[Hashable], bool],
        *,
        check_interval: float = 5.0,
        maximum_backoff: float = 300.0,
        notification_callback: Optional[Callable[[Hashable, bool, int], None]] = None,
    ) -> None:
        self.clients_provider = clients_provider
        self.login_callback = login_callback
        self.check_interval = max(1.0, check_interval)
        self.maximum_backoff = max(self.check_interval, maximum_backoff)
        self.notification_callback = notification_callback
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._failure_counts: dict[Hashable, int] = {}
        self._next_attempt_times: dict[Hashable, float] = {}
        self._lifecycle_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Return whether the worker thread is currently active."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the worker once; repeated calls are harmless."""
        with self._lifecycle_lock:
            self._stop_event.clear()
            if self.is_running:
                return
            self._thread = threading.Thread(
                target=self._run,
                name="SRunPy-Reconnect",
                daemon=True,
            )
            self._thread.start()

    def set_check_interval(self, check_interval: float) -> None:
        """Update the polling interval; takes effect on the next cycle."""
        with self._lifecycle_lock:
            self.check_interval = max(1.0, check_interval)
            self.maximum_backoff = max(self.check_interval, self.maximum_backoff)

    def stop(self, timeout: float = 2.0) -> None:
        """Wake and stop the worker without waiting through a backoff period."""
        with self._lifecycle_lock:
            worker_thread = self._thread
            self._stop_event.set()
        if worker_thread is not None and worker_thread is not threading.current_thread():
            worker_thread.join(timeout=timeout)
        with self._lifecycle_lock:
            if self._thread is worker_thread and not self.is_running:
                self._thread = None

    def run_iteration(self, current_time: Optional[float] = None) -> None:
        """Execute one monitoring pass; public to support deterministic tests."""
        iteration_time = time.monotonic() if current_time is None else current_time
        clients = dict(self.clients_provider())
        active_keys = set(clients)

        for stale_key in set(self._failure_counts) - active_keys:
            self._failure_counts.pop(stale_key, None)
            self._next_attempt_times.pop(stale_key, None)

        for interface_key in list(clients):
            if self._stop_event.is_set():
                return

            client = self.clients_provider().get(interface_key)
            if client is None:
                continue

            try:
                is_available, is_online, _ = client.is_connected()
            except Exception:
                is_available, is_online = False, False

            if is_online:
                self._reset_failures(interface_key)
                continue
            if not is_available:
                continue
            if iteration_time < self._next_attempt_times.get(interface_key, 0.0):
                continue

            try:
                login_succeeded = bool(self.login_callback(interface_key))
            except Exception:
                login_succeeded = False

            if login_succeeded:
                self._reset_failures(interface_key)
                failure_count = 0
            else:
                failure_count = self._failure_counts.get(interface_key, 0) + 1
                self._failure_counts[interface_key] = failure_count
                backoff_seconds = min(
                    self.maximum_backoff,
                    self.check_interval * (2 ** min(failure_count - 1, 8)),
                )
                self._next_attempt_times[interface_key] = iteration_time + backoff_seconds

            if self.notification_callback is not None:
                self.notification_callback(interface_key, login_succeeded, failure_count)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_iteration()
            self._stop_event.wait(self.check_interval)

    def _reset_failures(self, interface_key: Hashable) -> None:
        self._failure_counts.pop(interface_key, None)
        self._next_attempt_times.pop(interface_key, None)
