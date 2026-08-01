"""Configuration coordination: persistence, pure validation and the app-state DTO.

This layer owns the application configuration: atomic load/save, the pure
gateway/IP validation used by the transactional settings save, and the DTO the
WebView API projects to the frontend. It performs no network I/O and owns no
background services.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from srunpy import __version__
from srunpy.config import (
    ConfigStore,
    WindowsDPAPICredentialProtector,
    get_default_config_path,
    get_legacy_config_path,
)
from srunpy.ip_utils import get_local_ipv4_addresses
from srunpy.windows_integration import LEGACY_AES_KEY, MyAES

IpValidator = Callable[[str], bool]
DomainResolver = Callable[[str], Tuple[bool, str]]


def load_config() -> Dict[str, Any]:
    """
    Load configuration from file with AES decryption.
    使用 AES 解密从文件加载配置。

    Returns / 返回:
        Configuration dictionary / 配置字典
    """
    legacy_cipher = MyAES(key=LEGACY_AES_KEY)
    store = ConfigStore(
        get_default_config_path(),
        WindowsDPAPICredentialProtector(),
        legacy_config_path=get_legacy_config_path(),
        legacy_password_decryptor=lambda ciphertext: legacy_cipher.decode_aes(
            ciphertext.encode("ascii")
        ),
    )
    return store.load()


def save_config(config: Dict[str, Any]) -> None:
    """
    Save configuration to file with AES encryption.
    使用 AES 加密将配置保存到文件。

    Args / 参数:
        config: Configuration dictionary / 配置字典
    """
    legacy_cipher = MyAES(key=LEGACY_AES_KEY)
    store = ConfigStore(
        get_default_config_path(),
        WindowsDPAPICredentialProtector(),
        legacy_config_path=get_legacy_config_path(),
        legacy_password_decryptor=lambda ciphertext: legacy_cipher.decode_aes(
            ciphertext.encode("ascii")
        ),
    )
    store.save(config)


class ConfigCoordinator:
    """Pure configuration operations with no side effects on services."""

    @staticmethod
    def parse_gateway(
        gateway: str,
        default_host: str,
        default_ip: str,
        is_ip_address: IpValidator,
        is_domain: DomainResolver,
    ) -> Tuple[str, str]:
        """
        Resolve a gateway into (hostname, ip), validating it first.

        Args / 参数:
            gateway: Gateway address / 网关地址
            default_host: Hostname fallback / 主机名回退
            default_ip: IP fallback / IP 回退
            is_ip_address: IP test / IP 判定函数
            is_domain: Domain resolver / 域名解析函数

        Returns / 返回:
            Tuple of (hostname, ip) / (主机名, IP) 的元组

        Raises / 抛出:
            ValueError: If gateway cannot be resolved / 如果无法解析网关
        """
        target = gateway.strip() if gateway else ""
        if not target:
            return default_host, default_ip
        if is_ip_address(target):
            return "", target
        is_valid_domain, resolved_ip = is_domain(target)
        if is_valid_domain and resolved_ip:
            return target, resolved_ip
        raise ValueError("无法解析网关地址，请检查输入")

    @staticmethod
    def normalize_ip_selection(
        selected_ips: Optional[List[Optional[str]]],
    ) -> List[Optional[str]]:
        """De-duplicate and keep only locally-available IPs (pure, no mutation)."""
        if selected_ips is None:
            return []
        normalized: List[Optional[str]] = []
        available = set(get_local_ipv4_addresses())
        for ip in selected_ips:
            if ip in (None, "", "null"):
                normalized.append(None)
            elif ip in available:
                normalized.append(ip)
        # 去除重复项同时保留顺序
        ordered: List[Optional[str]] = []
        for ip in normalized:
            if ip not in ordered:
                ordered.append(ip)
        return ordered

    @staticmethod
    def build_app_state(
        config: Dict[str, Any],
        is_upto_date: bool,
    ) -> Dict[str, Any]:
        """Project named UI state without exposing the stored plaintext password."""
        return {
            "version": __version__,
            "username": config.get("username", ""),
            "has_password": bool(config.get("password", "")),
            "auto_login": config.get("auto_login", False),
            "start_with_windows": config.get("start_with_windows", False),
            "update_available": is_upto_date,
            "gateway": config.get("srun_host") if config.get("srun_host") else config.get("host_ip"),
            "self_service": config.get("self_service", ""),
            "active_ip": config.get("active_ip"),
            "selected_ips": list(config.get("local_ips", [])),
            "available_ips": get_local_ipv4_addresses(),
            "reconnect_interval": config.get("sleeptime", 5),
            "allow_unverified_tls": config.get("allow_unverified_tls", False),
            "allow_insecure_http": config.get("allow_insecure_http", False),
            "traffic_sampling_enabled": config.get("traffic_sampling_enabled", True),
            "traffic_sample_interval": config.get("traffic_sample_interval", 1.0),
            "traffic_history_enabled": config.get("traffic_history_enabled", True),
            "traffic_retention_days": config.get("traffic_retention_days", 7),
        }

    @staticmethod
    def validate_update(
        settings: Dict[str, Any],
        current: Dict[str, Any],
        is_ip_address: IpValidator,
        is_domain: DomainResolver,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Validate a full settings candidate against the current config.

        Returns a (candidate, errors) tuple. On any error the candidate is not
        meant to be committed; the caller must leave memory, disk and services
        untouched.
        """
        candidate = dict(current)
        validation_errors: List[str] = []

        gateway = str(settings.get("gateway", "")).strip()
        self_service = str(settings.get("self_service", "")).strip()
        try:
            resolved_host, resolved_ip = ConfigCoordinator.parse_gateway(
                gateway,
                current.get("srun_host", ""),
                current.get("host_ip", ""),
                is_ip_address,
                is_domain,
            )
        except ValueError:
            validation_errors.append("无法解析网关地址，请检查输入")
            resolved_host = candidate["srun_host"]
            resolved_ip = candidate["host_ip"]

        try:
            reconnect_interval = int(
                settings.get("reconnect_interval", current.get("sleeptime", 5))
            )
        except (TypeError, ValueError):
            validation_errors.append("重连间隔必须是整数")
            reconnect_interval = current.get("sleeptime", 5)
        else:
            if not 3 <= reconnect_interval <= 300:
                validation_errors.append("重连间隔必须在 3 到 300 秒之间")

        selected_ips = settings.get("selected_ips")
        active_ip = settings.get("active_ip")
        normalized_ips: List[Optional[str]] = []
        if selected_ips is not None:
            normalized_ips = ConfigCoordinator.normalize_ip_selection(selected_ips)
            if (
                active_ip is not None
                and normalized_ips
                and active_ip not in normalized_ips
            ):
                validation_errors.append("所选活动接口无效")

        try:
            sample_interval = float(
                settings.get("sample_interval", current.get("traffic_sample_interval", 1.0))
            )
        except (TypeError, ValueError):
            validation_errors.append("采样间隔必须是数字")
            sample_interval = current.get("traffic_sample_interval", 1.0)
        else:
            if not 0.5 <= sample_interval <= 5.0:
                validation_errors.append("采样间隔必须在 0.5 到 5 秒之间")

        try:
            retention_days = int(
                settings.get("retention_days", current.get("traffic_retention_days", 7))
            )
        except (TypeError, ValueError):
            validation_errors.append("历史保留天数必须是整数")
            retention_days = current.get("traffic_retention_days", 7)
        else:
            if not 1 <= retention_days <= 30:
                validation_errors.append("历史保留天数必须在 1 到 30 天之间")

        if validation_errors:
            return candidate, validation_errors

        # All validations passed — commit the full candidate.
        candidate["srun_host"] = resolved_host
        candidate["host_ip"] = resolved_ip
        candidate["self_service"] = self_service
        candidate["sleeptime"] = reconnect_interval
        candidate["allow_unverified_tls"] = bool(settings.get("allow_unverified_tls"))
        candidate["allow_insecure_http"] = bool(settings.get("allow_insecure_http"))
        candidate["traffic_sampling_enabled"] = bool(settings.get("enabled", True))
        candidate["traffic_sample_interval"] = sample_interval
        candidate["traffic_history_enabled"] = bool(settings.get("history_enabled", True))
        candidate["traffic_retention_days"] = retention_days
        if selected_ips is not None:
            candidate["local_ips"] = normalized_ips
            if normalized_ips:
                candidate["active_ip"] = (
                    active_ip if active_ip in normalized_ips else normalized_ips[0]
                )
            else:
                candidate["active_ip"] = None

        return candidate, []
