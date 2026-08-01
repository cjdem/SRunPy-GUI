"""Normalize account metrics returned by heterogeneous SRun gateways."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized_value = str(value).strip()
    return normalized_value or None


def _normalize_non_negative_integer(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not normalized_value.is_finite() or normalized_value < 0:
        return None
    integral_value = normalized_value.to_integral_value()
    if normalized_value != integral_value:
        return None
    return int(integral_value)


def _normalize_balance(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not normalized_value.is_finite() or normalized_value < 0:
        return None
    return format(normalized_value, "f")


@dataclass(frozen=True)
class AccountMetrics:
    """Stable, JSON-serializable account fields safe for presentation."""

    username: Optional[str]
    online_ip: Optional[str]
    account_total_bytes: Optional[int]
    balance: Optional[str]
    online_duration_seconds: Optional[int]
    capabilities: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_account_metrics(
    payload: Optional[Mapping[str, Any]],
    *,
    is_online: bool,
) -> AccountMetrics:
    """Convert one gateway response without retaining or logging its raw payload."""
    source = payload if isinstance(payload, Mapping) else {}
    username = _normalize_text(source.get("user_name")) if is_online else None
    online_ip = (
        _normalize_text(source.get("online_ip") or source.get("client_ip"))
        if is_online
        else None
    )
    account_total_bytes = (
        _normalize_non_negative_integer(source.get("sum_bytes")) if is_online else None
    )
    balance = _normalize_balance(source.get("user_balance")) if is_online else None

    # 在线时长与账号/余额/流量一样，只在确认在线时才是可信的；离线时必须清空，
    # 否则残留载荷中的陈旧 online_seconds 会被当作活跃会话展示。
    online_duration_seconds = None
    if is_online:
        for field_name in ("online_seconds", "online_time", "user_online_time"):
            candidate_value = _normalize_non_negative_integer(source.get(field_name))
            if candidate_value is not None:
                online_duration_seconds = candidate_value
                break

    return AccountMetrics(
        username=username,
        online_ip=online_ip,
        account_total_bytes=account_total_bytes,
        balance=balance,
        online_duration_seconds=online_duration_seconds,
        capabilities={
            "account_total_bytes": account_total_bytes is not None,
            "balance": balance is not None,
            "online_duration": online_duration_seconds is not None,
        },
    )
