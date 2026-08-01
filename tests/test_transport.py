import threading
import time
from unittest.mock import Mock

import pytest
from requests.exceptions import SSLError, Timeout

from srunpy.errors import (
    GatewayUnavailableError,
    RequestTimeoutError,
    TLSVerificationError,
)
from srunpy.srun import Srun_Py


def test_default_transport_is_verified_https_only() -> None:
    client = Srun_Py("gateway.example.edu", "192.0.2.10")

    candidates = client._build_request_candidates()

    assert [(candidate.base_url, candidate.verify_tls) for candidate in candidates] == [
        ("https://gateway.example.edu", True),
    ]


def test_insecure_transports_require_explicit_opt_in() -> None:
    client = Srun_Py(
        "gateway.example.edu",
        "192.0.2.10",
        allow_unverified_tls=True,
        allow_insecure_http=True,
    )

    candidates = client._build_request_candidates()

    assert [(candidate.base_url, candidate.verify_tls) for candidate in candidates] == [
        ("https://gateway.example.edu", True),
        ("https://192.0.2.10", False),
        ("http://gateway.example.edu", True),
        ("http://192.0.2.10", True),
    ]


def test_tls_error_does_not_silently_fall_back_to_http() -> None:
    client = Srun_Py("gateway.example.edu", "192.0.2.10")
    client.session.get = Mock(side_effect=SSLError("certificate rejected"))

    with pytest.raises(TLSVerificationError):
        client._request("/cgi-bin/rad_user_info")

    assert client.session.get.call_count == 1
    called_url = client.session.get.call_args.args[0]
    assert called_url.startswith("https://")


def test_every_request_uses_configured_timeout() -> None:
    client = Srun_Py(
        "gateway.example.edu",
        "192.0.2.10",
        request_timeout=(1.5, 2.5),
    )
    client.session.get = Mock(side_effect=Timeout("read timeout"))

    with pytest.raises(RequestTimeoutError):
        client._request("/cgi-bin/rad_user_info")

    assert client.session.get.call_args.kwargs["timeout"] == (1.5, 2.5)


def test_requests_after_close_raise_closed_error() -> None:
    client = Srun_Py("gateway.example.edu", "192.0.2.10")

    client.close()

    with pytest.raises(GatewayUnavailableError, match="已关闭"):
        client._request("/cgi-bin/rad_user_info")


def test_close_serializes_with_inflight_request() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def blocking_get(*_args: object, **_kwargs: object) -> None:
        calls.append("request-started")
        entered.set()
        release.wait(timeout=5)
        calls.append("request-finished")
        raise Timeout("timed out")

    client = Srun_Py("gateway.example.edu", "192.0.2.10")
    client.session.get = Mock(side_effect=blocking_get)

    request_error: list[str] = []

    def run_request() -> None:
        try:
            client._request("/cgi-bin/rad_user_info")
        except Exception as error:  # noqa: BLE001
            request_error.append(type(error).__name__)

    request_thread = threading.Thread(target=run_request)
    request_thread.start()
    assert entered.wait(timeout=2)

    closed_flags: list[bool] = []

    def run_close() -> None:
        client.close()
        closed_flags.append(True)

    close_thread = threading.Thread(target=run_close)
    close_thread.start()
    time.sleep(0.1)
    # close() must block (not finish) while a request still holds the client lock.
    assert closed_flags == []

    release.set()
    request_thread.join(timeout=3)
    close_thread.join(timeout=3)

    assert closed_flags == [True]
    assert calls == ["request-started", "request-finished"]
    assert request_error == ["RequestTimeoutError"]
    assert client._closed is True
