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
