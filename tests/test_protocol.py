import json

import pytest

from srunpy.errors import GatewayProtocolError
from srunpy.srun import Srun_Py, get_md5, get_sha1, get_xencode, parse_json_or_jsonp


def test_protocol_hash_vectors_are_stable() -> None:
    assert get_md5("secret", "0123456789abcdef") == "fea03f8ea7355c811537d43482714fca"
    assert get_sha1("srunpy") == "eb9551c86d492e9088173d9c01260a962cbb4c6f"


def test_xencode_vector_is_stable() -> None:
    encoded_message = get_xencode("message", "0123456789abcdef")

    assert encoded_message.encode("latin1").hex() == "5dc69dfcfaa4b393aba18efd"
    assert Srun_Py().get_base64(encoded_message) == "cMOnAgdYbeyl/ZE5"


def test_get_info_uses_valid_compact_json_for_special_characters() -> None:
    client = Srun_Py()

    info_text = client.get_info("student", "p'ass\\word", "10.0.0.8")

    assert json.loads(info_text) == {
        "username": "student",
        "password": "p'ass\\word",
        "ip": "10.0.0.8",
        "acid": "1",
        "enc_ver": "srun_bx1",
    }
    assert ": " not in info_text


@pytest.mark.parametrize(
    ("raw_response", "expected_payload"),
    [
        ('{"error":"ok"}', {"error": "ok"}),
        ('jQuery123({"error":"not_online_error"})', {"error": "not_online_error"}),
        (' callback ( {"challenge":"token"} ); ', {"challenge": "token"}),
    ],
)
def test_parse_json_or_jsonp_accepts_gateway_response_shapes(
    raw_response: str,
    expected_payload: dict[str, str],
) -> None:
    assert parse_json_or_jsonp(raw_response) == expected_payload


@pytest.mark.parametrize("raw_response", ["", "not-json", "[1, 2, 3]"])
def test_parse_json_or_jsonp_rejects_malformed_payloads(raw_response: str) -> None:
    with pytest.raises(GatewayProtocolError):
        parse_json_or_jsonp(raw_response)
