"""End-to-end protocol flow tests against a local fake Srun gateway."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import pytest

from srunpy.errors import AlreadyOnlineError, AuthenticationRejectedError
from srunpy.srun import Srun_Py, _RequestCandidate, get_md5


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "SRunPyTest/1.0"

    def log_message(self, *args: object) -> None:
        return

    def _send_json(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        gateway = self.server.gateway
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_response(302)
            self.send_header("Location", f"/cgi-bin/srun_portal?ac_id={gateway.ac_id}")
            self.end_headers()
            return

        if parsed.path == "/cgi-bin/rad_user_info":
            if not gateway.online:
                self._send_json({"error": "not_online_error", "client_ip": "10.0.0.8"})
                return
            self._send_json(
                {
                    "error": "ok",
                    "client_ip": "10.0.0.8",
                    "user_name": gateway.username,
                    "sum_bytes": 123456,
                    "user_balance": "5.00",
                    "online_time": 3600,
                }
            )
            return

        if parsed.path == "/cgi-bin/get_challenge":
            self._send_json({"error": "ok", "challenge": gateway.challenge_token})
            return

        if parsed.path == "/cgi-bin/srun_portal":
            gateway.portal_requests.append(params)
            action = params.get("action", [""])[0]
            if action == "login":
                if gateway.login_error:
                    self._send_json(
                        {
                            "error": gateway.login_error,
                            "error_msg": gateway.login_error_msg,
                        }
                    )
                    return
                gateway.online = True
                self._send_json({"error": "ok"})
                return
            if action == "logout":
                if gateway.portal_logout_error:
                    self._send_json({"error": gateway.portal_logout_error})
                    return
                gateway.online = False
                self._send_json({"error": "logout_ok"})
                return
            self._send_json({"error": "ok"})
            return

        if parsed.path == "/cgi-bin/rad_user_dm":
            gateway.rad_user_dm_calls += 1
            gateway.online = False
            self._send_text("ok")
            return

        self.send_response(404)
        self.end_headers()


class GatewayServer:
    def __init__(self) -> None:
        self.ac_id = "3"
        self.online = False
        self.username = "student"
        self.challenge_token = "0123456789abcdef"
        self.portal_logout_error: Optional[str] = None
        self.login_error: Optional[str] = None
        self.login_error_msg: Optional[str] = None
        self.portal_requests: List[Dict[str, List[str]]] = []
        self.rad_user_dm_calls = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        self.httpd.gateway = self
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="SRunPyTestGateway",
            daemon=True,
        )
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def gateway_server() -> GatewayServer:
    server = GatewayServer()
    yield server
    server.close()


def make_client(server: GatewayServer) -> Srun_Py:
    client = Srun_Py(
        f"127.0.0.1:{server.port}",
        f"127.0.0.1:{server.port}",
    )
    client._build_request_candidates = lambda: [
        _RequestCandidate(f"http://127.0.0.1:{server.port}", verify_tls=True)
    ]
    return client


def test_login_success_updates_acid_and_posts_protocol_params(
    gateway_server: GatewayServer,
) -> None:
    server = gateway_server
    client = make_client(server)

    assert client.login("student", "secret") is True
    assert server.online is True
    assert server.ac_id == "3"

    login_request = server.portal_requests[-1]
    assert login_request["action"] == ["login"]
    assert login_request["username"] == ["student"]
    assert login_request["password"] == [
        "{MD5}" + get_md5("secret", server.challenge_token)
    ]
    assert login_request["ac_id"] == ["3"]
    assert login_request["ip"] == ["10.0.0.8"]
    assert login_request["info"][0].startswith("{SRBX1}")


def test_login_raises_when_already_online(gateway_server: GatewayServer) -> None:
    server = gateway_server
    server.online = True
    server.username = "student"
    client = make_client(server)

    with pytest.raises(AlreadyOnlineError):
        client.login("student", "secret")

    assert server.portal_requests == []


def test_login_rejection_returns_false_with_user_message(
    gateway_server: GatewayServer,
) -> None:
    server = gateway_server
    server.login_error = "auth"
    server.login_error_msg = "用户名或密码错误"
    client = make_client(server)

    assert client.login("student", "wrong") is False
    assert isinstance(client.last_error, AuthenticationRejectedError)
    assert "用户名或密码错误" in client.last_error.message


def test_update_acid_parses_redirect_query(gateway_server: GatewayServer) -> None:
    server = gateway_server
    server.ac_id = "7"
    client = make_client(server)

    client.update_acid()

    assert client.ac_id == "7"


def test_is_connected_reports_offline_then_online(gateway_server: GatewayServer) -> None:
    server = gateway_server
    client = make_client(server)

    available, online, payload = client.is_connected()
    assert (available, online) == (True, False)
    assert payload["error"] == "not_online_error"

    server.online = True
    server.username = "student"
    available, online, payload = client.is_connected()
    assert (available, online) == (True, True)
    assert payload["user_name"] == "student"


def test_logout_uses_portal_confirmation(gateway_server: GatewayServer) -> None:
    server = gateway_server
    server.online = True
    server.username = "student"
    client = make_client(server)

    assert client.logout() is True
    assert server.online is False
    assert server.rad_user_dm_calls == 0
    assert server.portal_requests[-1]["action"] == ["logout"]


def test_logout_falls_back_to_classic_endpoint(gateway_server: GatewayServer) -> None:
    server = gateway_server
    server.online = True
    server.username = "student"
    server.portal_logout_error = "0"
    client = make_client(server)

    assert client.logout() is True
    assert server.rad_user_dm_calls == 1
    assert server.online is False
