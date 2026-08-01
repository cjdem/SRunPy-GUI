import threading
from collections.abc import Callable

from srunpy.reconnect import ReconnectService


class FakeConnectionClient:
    def __init__(self, status: tuple[bool, bool, object]) -> None:
        self.status = status

    def is_connected(self) -> tuple[bool, bool, object]:
        return self.status


def test_offline_available_interface_is_reconnected() -> None:
    client = FakeConnectionClient((True, False, {}))
    login_calls: list[str] = []
    service = ReconnectService(
        lambda: {"wifi": client},
        lambda interface: login_calls.append(str(interface)) or True,
    )

    service.run_iteration(current_time=100.0)

    assert login_calls == ["wifi"]


def test_unavailable_or_online_interface_is_not_reconnected() -> None:
    clients = {
        "unavailable": FakeConnectionClient((False, False, {})),
        "online": FakeConnectionClient((True, True, {})),
    }
    login_calls: list[str] = []
    service = ReconnectService(
        lambda: clients,
        lambda interface: login_calls.append(str(interface)) or True,
    )

    service.run_iteration(current_time=100.0)

    assert login_calls == []


def test_failed_interfaces_use_independent_bounded_backoff() -> None:
    clients = {
        "wifi": FakeConnectionClient((True, False, {})),
        "ethernet": FakeConnectionClient((True, False, {})),
    }
    login_results: dict[str, Callable[[], bool]] = {
        "wifi": lambda: False,
        "ethernet": lambda: True,
    }
    login_calls: list[str] = []

    def login(interface: object) -> bool:
        interface_name = str(interface)
        login_calls.append(interface_name)
        return login_results[interface_name]()

    service = ReconnectService(
        lambda: clients,
        login,
        check_interval=5.0,
        maximum_backoff=20.0,
    )

    service.run_iteration(current_time=100.0)
    service.run_iteration(current_time=104.0)
    service.run_iteration(current_time=105.0)
    service.run_iteration(current_time=109.0)
    service.run_iteration(current_time=115.0)

    assert login_calls.count("wifi") == 3
    assert login_calls.count("ethernet") == 5


def test_stop_is_idempotent_when_service_was_not_started() -> None:
    service = ReconnectService(lambda: {}, lambda _: True)

    service.stop()
    service.stop()

    assert service.is_running is False


def test_set_check_interval_updates_polling_interval_in_place() -> None:
    service = ReconnectService(
        lambda: {},
        lambda _: True,
        check_interval=5.0,
        maximum_backoff=20.0,
    )

    service.set_check_interval(10.0)
    assert service.check_interval == 10.0
    assert service.maximum_backoff == 20.0

    service.set_check_interval(50.0)
    assert service.maximum_backoff == 50.0


def test_start_clears_stop_event_while_worker_is_stopping() -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocking_login(_: object) -> bool:
        entered.set()
        release.wait(timeout=5)
        return True

    client = FakeConnectionClient((True, False, {}))
    service = ReconnectService(
        lambda: {"wifi": client},
        blocking_login,
        check_interval=1.0,
    )

    service.start()
    assert entered.wait(timeout=2)
    entered.clear()

    service.stop()
    assert service.is_running

    service.start()
    release.set()
    assert entered.wait(timeout=2)
    release.set()

    service.stop()
    assert service.is_running is False
