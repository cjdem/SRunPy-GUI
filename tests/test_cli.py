import io
import sys

import pytest

import srunpy
from srunpy import entry


class FakeClient:
    login_result = True
    logout_result = True
    construction_kwargs: list = []
    close_call_count = 0

    def __init__(self, **kwargs: object) -> None:
        FakeClient.construction_kwargs.append(kwargs)
        self.close_calls = 0

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_calls += 1
        FakeClient.close_call_count += 1

    def login(self, username: str, password: str) -> bool:
        assert username == "student"
        assert password == "secret"
        return self.login_result

    def logout(self) -> bool:
        return self.logout_result


def prepare_cli(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    FakeClient.construction_kwargs = []
    FakeClient.close_call_count = 0
    monkeypatch.setattr(sys, "argv", ["srunpy-cli", *arguments])
    monkeypatch.setattr(srunpy, "SrunClient", FakeClient)
    monkeypatch.setattr(entry, "get_local_ipv4_addresses", lambda: [])


def test_cli_reports_unsuccessful_login_with_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeClient.login_result = False
    prepare_cli(monkeypatch, "--login", "--username", "student", "--passwd", "secret")

    with pytest.raises(SystemExit) as exit_info:
        entry.Cli()

    assert exit_info.value.code == 1
    assert "登录失败" in capsys.readouterr().out


def test_cli_successful_login_does_not_raise_failure_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeClient.login_result = True
    prepare_cli(monkeypatch, "--login", "--username", "student", "--passwd", "secret")

    entry.Cli()

    assert "登录成功" in capsys.readouterr().out


def test_cli_rejects_multiple_operation_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    prepare_cli(monkeypatch, "--login", "--logout")

    with pytest.raises(SystemExit) as exit_info:
        entry.Cli()

    assert exit_info.value.code == 2


def test_cli_help_reconfigures_legacy_windows_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.BytesIO()
    legacy_stream = io.TextIOWrapper(output, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", legacy_stream)
    prepare_cli(monkeypatch, "--help")

    with pytest.raises(SystemExit) as exit_info:
        entry.Cli()

    legacy_stream.flush()
    assert exit_info.value.code == 0
    assert "深澜" in output.getvalue().decode("utf-8")


def test_cli_passes_security_flags_to_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeClient.login_result = True
    prepare_cli(
        monkeypatch,
        "--login",
        "--username",
        "student",
        "--passwd",
        "secret",
        "--allow-unverified-tls",
        "--allow-insecure-http",
    )

    entry.Cli()

    assert FakeClient.construction_kwargs
    for kwargs in FakeClient.construction_kwargs:
        assert kwargs.get("allow_unverified_tls") is True
        assert kwargs.get("allow_insecure_http") is True


def test_cli_security_flags_default_to_false(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeClient.login_result = True
    prepare_cli(monkeypatch, "--login", "--username", "student", "--passwd", "secret")

    entry.Cli()

    assert FakeClient.construction_kwargs
    for kwargs in FakeClient.construction_kwargs:
        assert kwargs.get("allow_unverified_tls") is False
        assert kwargs.get("allow_insecure_http") is False


def test_cli_closes_client_once_per_operation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeClient.login_result = True
    prepare_cli(monkeypatch, "--login", "--username", "student", "--passwd", "secret")

    entry.Cli()

    assert FakeClient.close_call_count == 1


def test_cli_closes_client_after_unsuccessful_login(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeClient.login_result = False
    prepare_cli(monkeypatch, "--login", "--username", "student", "--passwd", "secret")

    with pytest.raises(SystemExit) as exit_info:
        entry.Cli()

    assert exit_info.value.code == 1
    assert FakeClient.close_call_count == 1


def test_cli_reports_structured_srun_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from srunpy.errors import RequestTimeoutError

    def raise_timeout(self: FakeClient) -> None:
        raise RequestTimeoutError("网关请求超时")

    FakeClient.is_connected = raise_timeout  # type: ignore[method-assign]
    prepare_cli(monkeypatch, "--info")

    with pytest.raises(SystemExit) as exit_info:
        entry.Cli()

    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert "[request_timeout]" in output
    assert "网关请求超时" in output


def test_cli_describe_error_falls_back_to_plain_message() -> None:
    assert entry._describe_error(ValueError("boom")) == "boom"
    from srunpy.errors import GatewayUnavailableError

    assert (
        entry._describe_error(GatewayUnavailableError("网关不可达"))
        == "[gateway_unavailable] 网关不可达"
    )
