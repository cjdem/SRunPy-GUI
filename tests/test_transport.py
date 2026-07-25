from unittest.mock import Mock

import pytest
from requests.exceptions import SSLError, Timeout

from srunpy.errors import RequestTimeoutError, TLSVerificationError
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
