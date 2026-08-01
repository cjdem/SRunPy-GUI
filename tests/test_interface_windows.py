"""Windows-only tests for the desktop GUI backend."""

import os
import sys
import time

import pytest

win32_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="The desktop backend imports Windows-only dependencies.",
)

# Tests that need a real interactive Windows desktop session (DPAPI, tray, Start
# Menu shortcut) are skipped by default because GitHub Actions / headless runners
# have no interactive shell or credential store. Run them in a real Windows CI
# with SRUNPY_RUN_WINDOWS_DESKTOP=1 or select via -m windows_desktop.
windows_desktop_only = pytest.mark.skipif(
    os.environ.get("SRUNPY_RUN_WINDOWS_DESKTOP") != "1",
    reason=(
        "Requires a real interactive Windows desktop session; "
        "set SRUNPY_RUN_WINDOWS_DESKTOP=1 to run."
    ),
)

# The backend methods exposed to JavaScript through webview's window.expose().
EXPECTED_EXPOSED_API = {
    "get_app_state",
    "get_connection_status",
    "get_traffic_snapshot",
    "get_traffic_history",
    "update_settings",
    "clear_traffic_history",
    "perform_login",
    "perform_logout",
    "set_start_with_windows",
    "set_auto_login",
    "start_self_service",
    "open_releases_page",
    "probe_gateway_ips",
    "set_active_client_ip",
}

@win32_only
def test_probe_gateway_ips_closes_every_probe_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import srunpy.interface as interface

    class FakeClient:
        instances: list["FakeClient"] = []

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.closed = False
            self.args = args
            self.kwargs = kwargs
            FakeClient.instances.append(self)

        def is_connected(self) -> tuple[bool, bool, object]:
            return True, False, {}

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(interface, "SrunClient", FakeClient)
    monkeypatch.setattr(
        interface,
        "get_local_ipv4_addresses",
        lambda: ["10.0.0.2", "10.0.0.3"],
    )
    monkeypatch.setattr(
        interface,
        "is_domain",
        lambda address: (True, "192.0.2.10"),
    )

    backend = object.__new__(interface.GUIBackend)
    backend.allow_unverified_tls = False
    backend.allow_insecure_http = False
    backend.srun_host = "gw.example.edu"
    backend.host_ip = "192.0.2.10"
    backend.self_service = "zfw.example.edu"

    result = backend.probe_gateway_ips("gw.example.edu")

    assert result["ok"] is True
    assert len(FakeClient.instances) == 3
    assert all(client.closed for client in FakeClient.instances)


@win32_only
def test_reconnect_notification_uses_winotify_and_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import srunpy.interface as interface

    class FakeThread:
        def __init__(self, *, target: object, name: str = "", daemon: bool = False) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(interface.threading, "Thread", FakeThread)

    notifications: list[dict[str, object]] = []

    class FakeNotification:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def show(self) -> None:
            notifications.append(self.kwargs)

    monkeypatch.setattr(interface, "Notification", FakeNotification)

    backend = object.__new__(interface.GUIBackend)

    backend._notify_reconnect_result("10.0.0.2", True, 0)
    backend._notify_reconnect_result("10.0.0.2", False, 1)
    backend._notify_reconnect_result("10.0.0.2", False, 2)

    assert len(notifications) == 2
    assert notifications[0]["app_id"] == "SRunPy"
    assert notifications[0]["msg"] == "IP 10.0.0.2 \u81ea\u52a8\u767b\u5f55\u6210\u529f"
    assert notifications[1]["msg"] == "IP 10.0.0.2 \u81ea\u52a8\u767b\u5f55\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8d26\u53f7\u6216\u7f51\u7edc"


@win32_only
def test_sync_reconnect_service_reuses_instance_and_updates_interval() -> None:
    import srunpy.interface as interface

    backend = object.__new__(interface.GUIBackend)
    backend.sleeptime = 5
    backend.auto_login = False
    backend.srun_clients = {}
    backend.qt_backend = False
    backend.reconnect_service = None

    backend._sync_reconnect_service()
    first_service = backend.reconnect_service
    assert first_service is not None

    backend.sleeptime = 12
    backend._sync_reconnect_service()

    assert backend.reconnect_service is first_service
    assert backend.reconnect_service.check_interval == 12.0


@win32_only
def test_interface_reexports_windows_integration_symbols() -> None:
    """entry.py and tests import the tray/shortcut names from srunpy.interface;
    the facade must keep re-exporting them after the Windows layer split."""
    import srunpy.interface as interface
    import srunpy.windows_integration as windows_integration

    for name in (
        "TaskbarIcon",
        "create_lnk",
        "delete_lnk",
        "check_lnk",
        "get_Color_Mode",
        "get_Update",
        "MyAES",
        "LEGACY_AES_KEY",
        "start_lnk_path",
        "legacy_start_lnk_path",
    ):
        assert hasattr(interface, name), f"interface must re-export {name}"
        assert getattr(interface, name) is getattr(windows_integration, name)


@win32_only
def test_delete_lnk_removes_current_and_legacy_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import srunpy.interface as interface
    import srunpy.windows_integration as windows_integration

    removed: list[str] = []
    shortcut_paths = {
        interface.start_lnk_path,
        interface.legacy_start_lnk_path,
    }
    # delete_lnk now lives in the Windows integration layer; patch its module.
    monkeypatch.setattr(
        windows_integration.os.path,
        "exists",
        lambda path: path in shortcut_paths,
    )
    monkeypatch.setattr(
        windows_integration.os,
        "remove",
        lambda path: removed.append(str(path)),
    )

    interface.delete_lnk()

    assert set(removed) == shortcut_paths

# --- Single-instance mutex behavior ------------------------------------------
def test_single_instance_mutex_lifecycle_with_fake_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check mutex ownership/close logic without requiring a Windows kernel."""
    import ctypes

    import srunpy.single_instance as single_instance

    class _CallableCData:
        """Stands in for a ctypes function so .argtypes/.restype can be set."""

        def __init__(self, fn: object) -> None:
            self.fn = fn

        def __call__(self, *args: object) -> object:
            return self.fn(*args)

    class FakeKernel32:
        def __init__(self) -> None:
            self.created: list[str] = []
            self.closed: list[int] = []
            self.last_error = 0
            self.CreateMutexW = _CallableCData(self._create_mutex)

        def _create_mutex(self, _attrs: object, _initial: object, name: str) -> int:
            self.created.append(name)
            return 0xABC

        def GetLastError(self) -> int:
            return self.last_error

        def CloseHandle(self, handle: int) -> None:
            self.closed.append(handle)

    kernel = FakeKernel32()

    class _FakeWindll:
        kernel32 = kernel

    monkeypatch.setattr(ctypes, "windll", _FakeWindll())

    mutex_name = "Local\\SRunPy.Desktop"

    first = single_instance.WindowsSingleInstance(mutex_name=mutex_name)
    assert first.is_already_running is False

    # A second CreateMutexW for the same name reports ERROR_ALREADY_EXISTS (183).
    kernel.last_error = 183
    second = single_instance.WindowsSingleInstance(mutex_name=mutex_name)
    assert second.is_already_running is True
    assert kernel.created == [mutex_name, mutex_name]

    second.close()
    assert kernel.closed == [0xABC]
    # Closing twice is a no-op (handle already released / set to None).
    second.close()
    assert kernel.closed == [0xABC]

    # Context-manager usage calls close() on exit.
    kernel.last_error = 0
    with single_instance.WindowsSingleInstance(mutex_name=mutex_name) as managed:
        assert managed.is_already_running is False
    assert kernel.closed == [0xABC, 0xABC]


@win32_only
def test_single_instance_real_mutex_detects_second_instance() -> None:
    """Create a real named Windows mutex and confirm a second owner is detected."""
    import srunpy.single_instance as single_instance

    mutex_name = "Local\\SRunPy.Test.Mutex"
    first = single_instance.WindowsSingleInstance(mutex_name=mutex_name)
    try:
        second = single_instance.WindowsSingleInstance(mutex_name=mutex_name)
        try:
            assert second.is_already_running is True
        finally:
            second.close()
    finally:
        first.close()


# --- Background-thread exit ---------------------------------------------------
@win32_only
def test_shutdown_stops_background_services_and_terminates_threads() -> None:
    """GUIBackend.shutdown() must stop services, terminate their threads, and
    close pooled connections."""
    import threading

    import srunpy.interface as interface

    class FakeBackgroundService:
        """Lightweight in-process stand-in sharing the start/stop/thread shape
        of the real ReconnectService / TrafficMonitorService."""

        def __init__(self) -> None:
            self._stop_event = threading.Event()
            self._thread: threading.Thread | None = None
            self.stop_calls = 0

        def start(self) -> None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

        def _run(self) -> None:
            while not self._stop_event.is_set():
                self._stop_event.wait(0.02)

        @property
        def is_running(self) -> bool:
            return self._thread is not None and self._thread.is_alive()

        def stop(self) -> None:
            self.stop_calls += 1
            self._stop_event.set()
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)

    traffic_monitor = FakeBackgroundService()
    reconnect_service = FakeBackgroundService()
    traffic_monitor.start()
    reconnect_service.start()
    assert traffic_monitor.is_running
    assert reconnect_service.is_running

    closed_clients: list[object] = []

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True
            closed_clients.append(self)

    backend = object.__new__(interface.GUIBackend)
    backend.traffic_monitor = traffic_monitor
    backend.reconnect_service = reconnect_service
    backend._backend_lock = threading.RLock()
    backend.srun_clients = {None: FakeClient(), "10.0.0.2": FakeClient()}

    backend.shutdown()

    assert traffic_monitor.stop_calls == 1
    assert reconnect_service.stop_calls == 1
    assert not traffic_monitor.is_running
    assert not reconnect_service.is_running
    assert len(closed_clients) == 2
    assert all(client.closed for client in closed_clients)


@win32_only
def test_shutdown_tolerates_missing_clients_and_services() -> None:
    """shutdown() must be safe when no clients are pooled yet."""
    import threading

    import srunpy.interface as interface

    backend = object.__new__(interface.GUIBackend)
    backend.traffic_monitor = None
    backend.reconnect_service = None
    backend._backend_lock = threading.RLock()
    backend.srun_clients = {}

    # Must not raise when there is nothing to stop.
    backend.shutdown()

# --- WebView API exposure -----------------------------------------------------
@win32_only
def test_webview_exposes_expected_backend_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MainWindow.start_webview() must expose exactly the expected API and each
    exposed callable must be invocable."""
    import srunpy.interface as interface

    exposed_callables: list[object] = []

    class FakeWindow:
        def expose(self, *callables: object) -> None:
            exposed_callables.extend(callables)

    fake_window = FakeWindow()
    monkeypatch.setattr(interface.webview, "windows", [])
    monkeypatch.setattr(
        interface.webview,
        "create_window",
        lambda *_args, **_kwargs: fake_window,
    )
    monkeypatch.setattr(interface.webview, "start", lambda *_a, **_k: None)

    backend = object.__new__(interface.GUIBackend)
    backend.qt_backend = False

    window = interface.MainWindow(backend, open_window=False)
    window.start_webview()

    exposed_names = {
        getattr(callable_, "__name__", repr(callable_)) for callable_ in exposed_callables
    }
    assert exposed_names == EXPECTED_EXPOSED_API
    assert all(callable(callable_) for callable_ in exposed_callables)


# --- Tray icon (fake-based; no real desktop needed) ---------------------------
@win32_only
def test_taskbar_icon_stop_and_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """stop()/exit() on the tray icon must release the underlying icon."""
    import srunpy.interface as interface

    stop_count = 0

    class FakeIcon:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            nonlocal stop_count
            stop_count += 1

    icon = object.__new__(interface.TaskbarIcon)
    icon.should_exit = False
    icon.icon = FakeIcon()

    icon.stop()
    assert stop_count == 1

    icon.exit()
    assert icon.should_exit is True
    assert stop_count == 2


# --- Real interactive Windows desktop session (skipped by default) ------------
@win32_only
@windows_desktop_only
@pytest.mark.windows_desktop
def test_dpapi_credential_round_trip_real_session() -> None:
    """DPAPI protect/unprotect round-trip needs a real Windows credential store."""
    import srunpy.config as config

    protector = config.WindowsDPAPICredentialProtector()
    protected = protector.protect("sensitive-password")
    assert "sensitive-password" not in protected
    assert protector.unprotect(protected) == "sensitive-password"


# --- Transactional settings save ----------------------------------------------
def _make_settings_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    save_config_impl: object = None,
) -> tuple[object, object, list[dict[str, object]]]:
    """Build a minimally-wired GUIBackend for update_settings and return
    (backend, save_mock, saved_calls)."""
    import threading
    from unittest.mock import Mock

    import srunpy.interface as interface

    saved_calls: list[dict[str, object]] = []

    def fake_save(config: dict[str, object]) -> None:
        if save_config_impl is not None:
            save_config_impl(config)
        saved_calls.append(dict(config))

    monkeypatch.setattr(interface, "save_config", fake_save)
    monkeypatch.setattr(interface, "get_local_ipv4_addresses", lambda: ["10.0.0.2"])

    backend = object.__new__(interface.GUIBackend)
    backend._backend_lock = threading.RLock()
    backend.sleeptime = 60
    backend.traffic_sample_interval = 1.0
    backend.traffic_retention_days = 7
    backend.traffic_sampling_enabled = True
    backend.traffic_history_enabled = True
    backend.config = {
        "srun_host": "gw.example.edu",
        "host_ip": "192.0.2.10",
        "self_service": "zfw.example.edu",
        "sleeptime": 60,
        "allow_unverified_tls": False,
        "allow_insecure_http": False,
        "local_ips": ["10.0.0.2"],
        "active_ip": "10.0.0.2",
        "traffic_sampling_enabled": True,
        "traffic_sample_interval": 1.0,
        "traffic_history_enabled": True,
        "traffic_retention_days": 7,
    }
    backend.refresh_config = Mock()
    refresh_mock = backend.refresh_config
    return backend, refresh_mock, saved_calls


@win32_only
def test_update_settings_commits_full_candidate_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, refresh_mock, saved_calls = _make_settings_backend(monkeypatch)

    result = backend.update_settings(
        {
            "gateway": "192.0.2.99",
            "self_service": "zfw.example.edu",
            "reconnect_interval": 30,
            "selected_ips": ["10.0.0.2"],
            "active_ip": "10.0.0.2",
            "allow_unverified_tls": True,
            "allow_insecure_http": False,
            "enabled": True,
            "sample_interval": 2.0,
            "history_enabled": True,
            "retention_days": 14,
        }
    )

    assert result["ok"] is True
    assert len(saved_calls) == 1
    assert saved_calls[0]["sleeptime"] == 30
    assert saved_calls[0]["host_ip"] == "192.0.2.99"
    assert saved_calls[0]["allow_unverified_tls"] is True
    assert saved_calls[0]["traffic_sample_interval"] == 2.0
    assert saved_calls[0]["traffic_retention_days"] == 14
    refresh_mock.assert_called_once_with()


@win32_only
def test_update_settings_invalid_values_do_not_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, refresh_mock, saved_calls = _make_settings_backend(monkeypatch)

    result = backend.update_settings(
        {
            "gateway": "192.0.2.99",
            "self_service": "zfw.example.edu",
            "reconnect_interval": 1,  # out of [3, 300]
            "selected_ips": ["10.0.0.2"],
            "active_ip": "10.0.0.2",
            "allow_unverified_tls": False,
            "allow_insecure_http": False,
            "enabled": True,
            "sample_interval": 1.0,
            "history_enabled": True,
            "retention_days": 40,  # out of [1, 30]
        }
    )

    assert result["ok"] is False
    assert saved_calls == []
    refresh_mock.assert_not_called()
    # In-memory config must be untouched.
    assert backend.config["sleeptime"] == 60
    assert backend.config["host_ip"] == "192.0.2.10"


@win32_only
def test_update_settings_invalid_gateway_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import srunpy.interface as interface

    backend, refresh_mock, saved_calls = _make_settings_backend(monkeypatch)
    monkeypatch.setattr(interface, "is_domain", lambda address: (False, ""))

    result = backend.update_settings(
        {
            "gateway": "not-a-real-gateway",
            "self_service": "zfw.example.edu",
            "reconnect_interval": 30,
            "selected_ips": None,
            "active_ip": None,
            "allow_unverified_tls": False,
            "allow_insecure_http": False,
            "enabled": True,
            "sample_interval": 1.0,
            "history_enabled": True,
            "retention_days": 7,
        }
    )

    assert result["ok"] is False
    assert "网关" in result["message"]
    assert saved_calls == []
    refresh_mock.assert_not_called()
    assert backend.config["host_ip"] == "192.0.2.10"


@win32_only
def test_update_settings_save_failure_is_reported_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_save(_config: dict[str, object]) -> None:
        raise OSError("disk full")

    backend, refresh_mock, _ = _make_settings_backend(
        monkeypatch, save_config_impl=failing_save
    )

    result = backend.update_settings(
        {
            "gateway": "192.0.2.99",
            "self_service": "zfw.example.edu",
            "reconnect_interval": 30,
            "selected_ips": None,
            "active_ip": None,
            "allow_unverified_tls": False,
            "allow_insecure_http": False,
            "enabled": True,
            "sample_interval": 1.0,
            "history_enabled": True,
            "retention_days": 7,
        }
    )

    assert result["ok"] is False
    assert "保存设置失败" in result["message"]
    refresh_mock.assert_not_called()


# --- Concurrency: refresh / shutdown / auto-reconnect toggling -----------------
class _FakeRefreshClient:
    """SrunClient stand-in that records construction and close ordering."""

    instances: list["_FakeRefreshClient"] = []
    close_events: list[str] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.closed = False
        _FakeRefreshClient.instances.append(self)

    def is_connected(self) -> tuple[bool, bool, object]:
        return True, False, {}

    def close(self) -> None:
        self.closed = True
        _FakeRefreshClient.close_events.append(f"close:{id(self)}")


class _FakeRefreshReconnect:
    """ReconnectService stand-in that records stop/start ordering."""

    instances: list["_FakeRefreshReconnect"] = []
    stop_events: list[str] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.check_interval = float(kwargs.get("check_interval", 5.0))
        _FakeRefreshReconnect.instances.append(self)

    def stop(self) -> None:
        _FakeRefreshReconnect.stop_events.append(f"stop:{id(self)}")

    def start(self) -> None:
        _FakeRefreshReconnect.stop_events.append(f"start:{id(self)}")

    def set_check_interval(self, interval: float) -> None:
        self.check_interval = interval


class _FakeRefreshTrafficMonitor:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.sample_interval = kwargs.get("sample_interval")
        self.history_enabled = kwargs.get("history_enabled")
        self.retention_days = kwargs.get("retention_days")
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def update_selection(self, _ip: object, _gateway: object) -> None:
        pass


def _make_refresh_backend(monkeypatch: pytest.MonkeyPatch, config: dict[str, object]):
    """Build a GUIBackend whose refresh path runs against fakes, so the real
    `_refresh_config_inner` ordering can be asserted deterministically."""
    import threading

    import srunpy.interface as interface

    _FakeRefreshClient.instances = []
    _FakeRefreshClient.close_events = []
    _FakeRefreshReconnect.instances = []
    _FakeRefreshReconnect.stop_events = []

    backend = object.__new__(interface.GUIBackend)
    backend.config = dict(config)
    backend.qt_backend = False
    backend._backend_lock = threading.RLock()
    backend.reconnect_service = None
    backend.traffic_monitor = None

    # load_config returns the live in-memory config (as refresh mutates it), and
    # save_config never touches the real on-disk config.
    monkeypatch.setattr(interface, "load_config", lambda: backend.config)
    monkeypatch.setattr(interface, "save_config", lambda _config: None)
    monkeypatch.setattr(interface, "create_lnk", lambda **kwargs: None)
    monkeypatch.setattr(interface, "delete_lnk", lambda: None)
    monkeypatch.setattr(interface, "SrunClient", _FakeRefreshClient)
    monkeypatch.setattr(interface, "ReconnectService", _FakeRefreshReconnect)
    monkeypatch.setattr(interface, "TrafficHistoryStore", lambda path: object())
    monkeypatch.setattr(interface, "TrafficCounterProvider", lambda: object())
    monkeypatch.setattr(interface, "TrafficMonitorService", _FakeRefreshTrafficMonitor)
    return backend


@win32_only
def test_refresh_config_stops_reconnect_before_closing_old_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {
        "username": "student",
        "password": "",
        "pass_correct": False,
        "srun_host": "gw.example.edu",
        "host_ip": "192.0.2.10",
        "self_service": "zfw.example.edu",
        "sleeptime": 5,
        "auto_login": False,
        "start_with_windows": False,
        "local_ips": ["10.0.0.2"],
        "active_ip": "10.0.0.2",
        "allow_unverified_tls": False,
        "allow_insecure_http": False,
        "traffic_sampling_enabled": False,
        "traffic_sample_interval": 1.0,
        "traffic_history_enabled": False,
        "traffic_retention_days": 7,
    }
    backend = _make_refresh_backend(monkeypatch, config)

    # A running reconnect service that must be stopped before the pool is torn down.
    live_service = _FakeRefreshReconnect()
    backend.reconnect_service = live_service
    old_client = _FakeRefreshClient()
    backend.srun_clients = {None: old_client}

    backend._refresh_config_inner()

    # The pre-existing reconnect worker was stopped before the old pool was closed.
    assert _FakeRefreshReconnect.stop_events[0] == f"stop:{id(live_service)}"
    assert old_client.closed is True
    # New clients were built for the refreshed selection and none was closed yet.
    new_clients = [c for c in _FakeRefreshClient.instances if c is not old_client]
    assert len(new_clients) == len(backend.srun_clients)
    assert all(not client.closed for client in new_clients)
    assert backend.srun is not None
    # auto_login=False leaves the reconnect worker stopped.
    assert backend.reconnect_service is live_service
    assert backend.reconnect_service.check_interval == 5.0


@win32_only
def test_shutdown_closes_clients_after_inflight_request_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client blocked mid-request must finish before shutdown closes it; no
    use-after-close surfaces from the real Srun_Py lock."""
    import threading
    from unittest.mock import Mock

    from requests.exceptions import Timeout

    import srunpy.interface as interface
    from srunpy.srun import Srun_Py

    entered = threading.Event()
    release = threading.Event()

    def blocking_get(*_args: object, **_kwargs: object) -> None:
        entered.set()
        release.wait(timeout=5)
        raise Timeout("timed out")

    client = Srun_Py("gw.example.edu", "192.0.2.10")
    client.session.get = Mock(side_effect=blocking_get)

    request_finished: list[bool] = []

    def run_request() -> None:
        try:
            client._request("/cgi-bin/rad_user_info")
        except Exception:
            pass
        finally:
            request_finished.append(True)

    request_thread = threading.Thread(target=run_request)
    request_thread.start()
    assert entered.wait(timeout=2)

    backend = object.__new__(interface.GUIBackend)
    backend._backend_lock = threading.RLock()
    backend.traffic_monitor = None
    backend.reconnect_service = None
    backend.srun_clients = {None: client}

    shutdown_finished: list[bool] = []

    def run_shutdown() -> None:
        backend.shutdown()
        shutdown_finished.append(True)

    shutdown_thread = threading.Thread(target=run_shutdown)
    shutdown_thread.start()
    time.sleep(0.1)
    # shutdown() must not finish while the request still owns the client lock.
    assert shutdown_finished == []

    release.set()
    request_thread.join(timeout=3)
    shutdown_thread.join(timeout=3)

    assert request_finished == [True]
    assert shutdown_finished == [True]
    assert client._closed is True


@win32_only
def test_rapid_auto_login_toggle_keeps_reconnect_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flicking auto-login on/off must reuse one real reconnect service and leave
    its running state matching the final config value."""
    import srunpy.interface as interface
    from srunpy.reconnect import ReconnectService as _RealReconnectService

    config = {
        "username": "student",
        "password": "",
        "pass_correct": True,
        "srun_host": "gw.example.edu",
        "host_ip": "192.0.2.10",
        "self_service": "zfw.example.edu",
        "sleeptime": 5,
        "auto_login": False,
        "start_with_windows": False,
        "local_ips": ["10.0.0.2"],
        "active_ip": "10.0.0.2",
        "allow_unverified_tls": False,
        "allow_insecure_http": False,
        "traffic_sampling_enabled": False,
        "traffic_sample_interval": 1.0,
        "traffic_history_enabled": False,
        "traffic_retention_days": 7,
    }
    backend = _make_refresh_backend(monkeypatch, config)
    # Use the real ReconnectService so thread start/stop is actually exercised.
    monkeypatch.setattr(interface, "ReconnectService", _RealReconnectService)
    backend.reconnect_service = None
    backend.srun_clients = {}
    backend.pass_correct = True

    first_service = None
    for auto_login in (True, False, True, False, True, False):
        backend.config["auto_login"] = auto_login
        backend.auto_login = auto_login
        assert backend.set_auto_login(auto_login) is True
        assert backend.reconnect_service is not None
        if first_service is None:
            first_service = backend.reconnect_service
        # A single instance is reused across the whole flicker.
        assert backend.reconnect_service is first_service
        if backend.reconnect_service.is_running != auto_login:
            # is_running can lag thread start/stop by a scheduling tick; poll once.
            deadline = time.monotonic() + 1.0
            while (
                time.monotonic() < deadline
                and backend.reconnect_service.is_running != auto_login
            ):
                time.sleep(0.01)
        assert backend.reconnect_service.is_running is auto_login

    # The service ends stopped, matching the final config value.
    assert backend.reconnect_service.is_running is False