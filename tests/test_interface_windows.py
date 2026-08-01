"""Windows-only tests for the desktop GUI backend."""

import sys

import pytest

win32_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="The desktop backend imports Windows-only dependencies.",
)


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
    assert notifications[0]["msg"] == "IP 10.0.0.2 自动登录成功"
    assert notifications[1]["msg"] == "IP 10.0.0.2 自动登录失败，请检查账号或网络"


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
def test_delete_lnk_removes_current_and_legacy_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import srunpy.interface as interface

    removed: list[str] = []
    shortcut_paths = {interface.start_lnk_path, interface.legacy_start_lnk_path}
    monkeypatch.setattr(
        interface.os.path,
        "exists",
        lambda path: path in shortcut_paths,
    )
    monkeypatch.setattr(
        interface.os,
        "remove",
        lambda path: removed.append(str(path)),
    )

    interface.delete_lnk()

    assert set(removed) == shortcut_paths
