import socket

from srunpy.ip_utils import get_local_ipv4_addresses


class FakeSocket:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self._address = "192.0.2.7"

    def connect(self, address: object) -> None:
        self._address = "192.0.2.7"

    def getsockname(self) -> tuple[str, int]:
        return (self._address, 0)

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_returns_sorted_unique_addresses_without_loopback(monkeypatch) -> None:
    monkeypatch.setattr(socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        socket,
        "gethostbyname_ex",
        lambda _: (["host"], [], ["10.0.0.3", "127.0.0.1", "10.0.0.2"]),
    )

    def fake_getaddrinfo(
        host: object,
        port: object,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple]:
        if host is None:
            return [(socket.AF_INET, socket.SOCK_DGRAM, 6, "", ("10.0.0.4", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: FakeSocket())

    addresses = get_local_ipv4_addresses()

    assert addresses == ["10.0.0.2", "10.0.0.3", "10.0.0.4", "192.0.2.7"]
    assert "127.0.0.1" in get_local_ipv4_addresses(include_loopback=True)


def test_ignores_dns_failures_and_broken_route_socket(monkeypatch) -> None:
    monkeypatch.setattr(socket, "gethostname", lambda: "host")

    def raise_gaierror(*args: object, **kwargs: object) -> list[tuple]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "gethostbyname_ex", raise_gaierror)
    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)

    class BrokenSocket:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def connect(self, address: object) -> None:
            raise OSError("no route to host")

        def close(self) -> None:
            pass

        def __enter__(self) -> "BrokenSocket":
            return self

        def __exit__(self, *exc: object) -> None:
            self.close()

    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: BrokenSocket())

    assert get_local_ipv4_addresses() == []
