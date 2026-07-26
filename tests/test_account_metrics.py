from srunpy.account_metrics import normalize_account_metrics


def test_normalizes_online_account_fields_without_guessing_balance_unit() -> None:
    metrics = normalize_account_metrics(
        {
            "user_name": " student ",
            "client_ip": "10.0.0.8",
            "sum_bytes": "1073741824",
            "user_balance": "12.50",
            "online_time": "3600",
        },
        is_online=True,
    ).to_dict()

    assert metrics == {
        "username": "student",
        "online_ip": "10.0.0.8",
        "account_total_bytes": 1073741824,
        "balance": "12.50",
        "online_duration_seconds": 3600,
        "capabilities": {
            "account_total_bytes": True,
            "balance": True,
            "online_duration": True,
        },
    }


def test_rejects_missing_null_fractional_and_negative_numeric_fields() -> None:
    metrics = normalize_account_metrics(
        {
            "sum_bytes": "1.5",
            "user_balance": -1,
            "online_seconds": None,
        },
        is_online=True,
    )

    assert metrics.username is None
    assert metrics.account_total_bytes is None
    assert metrics.balance is None
    assert metrics.online_duration_seconds is None
    assert not any(metrics.capabilities.values())


def test_offline_payload_does_not_expose_stale_account_values() -> None:
    metrics = normalize_account_metrics(
        {"user_name": "student", "sum_bytes": 42, "user_balance": 10},
        is_online=False,
    )

    assert metrics.username is None
    assert metrics.account_total_bytes is None
    assert metrics.balance is None
