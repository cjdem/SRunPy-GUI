import sys

import pytest

import srunpy
from srunpy import entry


class FakeClient:
    login_result = True
    logout_result = True

    def __init__(self, **_: object) -> None:
        pass

    def login(self, username: str, password: str) -> bool:
        assert username == "student"
        assert password == "secret"
        return self.login_result

    def logout(self) -> bool:
        return self.logout_result


def prepare_cli(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
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
