"""Versioned, atomic application configuration and Windows credential protection."""

import base64
import ctypes
import ipaddress
import json
import os
import shutil
import tempfile
import threading
from copy import deepcopy
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

CONFIG_SCHEMA_VERSION = 3

DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "username": "",
    "password": "",
    "pass_correct": False,
    "srun_host": "gw.buaa.edu.cn",
    "self_service": "zfw.buaa.edu.cn",
    "host_ip": "10.200.21.4",
    "sleeptime": 5,
    "auto_login": False,
    "start_with_windows": False,
    "local_ips": [None],
    "active_ip": None,
    "allow_unverified_tls": False,
    "allow_insecure_http": False,
    "traffic_sampling_enabled": True,
    "traffic_sample_interval": 1.0,
    "traffic_history_enabled": True,
    "traffic_retention_days": 7,
}


class CredentialProtector(Protocol):
    """Protect and unprotect a credential for the current operating-system user."""

    def protect(self, plaintext: str) -> str:
        """Return a serialized protected credential."""

    def unprotect(self, protected_value: str) -> str:
        """Return plaintext from a serialized protected credential."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class WindowsDPAPICredentialProtector:
    """Protect credentials with Windows DPAPI in the current-user scope."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    @staticmethod
    def _create_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        data_buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(
            len(data),
            ctypes.cast(data_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        return blob, data_buffer

    def protect(self, plaintext: str) -> str:
        plaintext_blob, plaintext_buffer = self._create_blob(plaintext.encode("utf-8"))
        protected_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32

        succeeded = crypt32.CryptProtectData(
            ctypes.byref(plaintext_blob),
            "SRunPy credential",
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(protected_blob),
        )
        del plaintext_buffer
        if not succeeded:
            raise ctypes.WinError()

        try:
            protected_bytes = ctypes.string_at(protected_blob.pbData, protected_blob.cbData)
            return base64.b64encode(protected_bytes).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(protected_blob.pbData)

    def unprotect(self, protected_value: str) -> str:
        protected_bytes = base64.b64decode(protected_value, validate=True)
        protected_blob, protected_buffer = self._create_blob(protected_bytes)
        plaintext_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32

        succeeded = crypt32.CryptUnprotectData(
            ctypes.byref(protected_blob),
            None,
            None,
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(plaintext_blob),
        )
        del protected_buffer
        if not succeeded:
            raise ctypes.WinError()

        try:
            plaintext_bytes = ctypes.string_at(plaintext_blob.pbData, plaintext_blob.cbData)
            return plaintext_bytes.decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(plaintext_blob.pbData)


def get_default_config_path() -> Path:
    """Return the non-roaming per-user configuration path on Windows."""
    local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "SRunPy" / "config.json"


def get_legacy_config_path() -> Optional[Path]:
    """Return the former roaming configuration path when it differs."""
    roaming_app_data = os.environ.get("APPDATA")
    if not roaming_app_data:
        return None
    legacy_path = Path(roaming_app_data) / "SRunPy" / "config.json"
    return legacy_path if legacy_path != get_default_config_path() else None


class ConfigStore:
    """Load, migrate, and atomically save one application configuration file."""

    def __init__(
        self,
        config_path: Path,
        credential_protector: CredentialProtector,
        *,
        legacy_config_path: Optional[Path] = None,
        legacy_password_decryptor: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.config_path = config_path
        self.credential_protector = credential_protector
        self.legacy_config_path = legacy_config_path
        self.legacy_password_decryptor = legacy_password_decryptor
        self._lock = threading.RLock()

    def load(self) -> Dict[str, Any]:
        """Load configuration, recovering safely from missing or corrupt files."""
        with self._lock:
            self._migrate_legacy_location()
            if not self.config_path.exists():
                initial_config = deepcopy(DEFAULT_CONFIG)
                self.save(initial_config)
                return initial_config

            try:
                with self.config_path.open("r", encoding="utf-8") as config_file:
                    disk_config = json.load(config_file)
                if not isinstance(disk_config, dict):
                    raise ValueError("配置根节点必须是 JSON 对象")
            except (OSError, ValueError, json.JSONDecodeError):
                self._backup_corrupt_file()
                recovered_config = deepcopy(DEFAULT_CONFIG)
                self.save(recovered_config)
                return recovered_config

            config = self._normalize_config(disk_config)
            migrated = self._load_password(config, disk_config)
            if migrated or disk_config.get("schema_version") != CONFIG_SCHEMA_VERSION:
                self.save(config)
            return config

    def save(self, config: Mapping[str, Any]) -> None:
        """Write configuration atomically without mutating the caller's object."""
        with self._lock:
            disk_config = deepcopy(dict(config))
            plaintext_password = str(disk_config.pop("password", ""))
            disk_config.pop("process_id", None)
            disk_config["schema_version"] = CONFIG_SCHEMA_VERSION
            disk_config["protected_password"] = (
                self.credential_protector.protect(plaintext_password)
                if plaintext_password
                else ""
            )

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_file_descriptor, temporary_path_text = tempfile.mkstemp(
                prefix="config-",
                suffix=".tmp",
                dir=self.config_path.parent,
            )
            temporary_path = Path(temporary_path_text)
            try:
                with os.fdopen(temporary_file_descriptor, "w", encoding="utf-8") as config_file:
                    json.dump(disk_config, config_file, ensure_ascii=False, indent=2)
                    config_file.write("\n")
                    config_file.flush()
                    os.fsync(config_file.fileno())
                os.replace(temporary_path, self.config_path)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()

    def _normalize_config(self, disk_config: Mapping[str, Any]) -> Dict[str, Any]:
        config = deepcopy(DEFAULT_CONFIG)
        for key in DEFAULT_CONFIG:
            if key in disk_config and key != "password":
                config[key] = deepcopy(disk_config[key])

        for text_key in ("srun_host", "host_ip", "self_service"):
            raw_value = config.get(text_key)
            normalized_value = str(raw_value).strip() if raw_value is not None else ""
            config[text_key] = normalized_value
        if not config["srun_host"]:
            config["srun_host"] = DEFAULT_CONFIG["srun_host"]
        if not config["host_ip"]:
            config["host_ip"] = config["srun_host"]
        if not config["self_service"]:
            config["self_service"] = DEFAULT_CONFIG["self_service"]

        try:
            sleeptime = int(config.get("sleeptime", DEFAULT_CONFIG["sleeptime"]))
        except (TypeError, ValueError):
            sleeptime = DEFAULT_CONFIG["sleeptime"]
        config["sleeptime"] = min(max(sleeptime, 3), 300)

        normalized_ips: list[Optional[str]] = []
        raw_ips = config.get("local_ips")
        if isinstance(raw_ips, list):
            for raw_ip in raw_ips:
                if raw_ip in (None, "", "null"):
                    if None not in normalized_ips:
                        normalized_ips.append(None)
                    continue
                if not isinstance(raw_ip, str):
                    continue
                try:
                    ipaddress.IPv4Address(raw_ip)
                except ValueError:
                    continue
                if raw_ip not in normalized_ips:
                    normalized_ips.append(raw_ip)
        if not normalized_ips:
            normalized_ips = [None]
        config["local_ips"] = normalized_ips
        if config.get("active_ip") not in normalized_ips:
            config["active_ip"] = (
                None if normalized_ips == [None] else normalized_ips[0]
            )
        if not config.get("pass_correct"):
            config["auto_login"] = False
        config["traffic_sampling_enabled"] = bool(config.get("traffic_sampling_enabled"))
        config["traffic_history_enabled"] = bool(config.get("traffic_history_enabled"))
        try:
            sample_interval = float(config.get("traffic_sample_interval", 1.0))
        except (TypeError, ValueError):
            sample_interval = 1.0
        config["traffic_sample_interval"] = min(max(sample_interval, 0.5), 5.0)
        try:
            retention_days = int(config.get("traffic_retention_days", 7))
        except (TypeError, ValueError):
            retention_days = 7
        config["traffic_retention_days"] = min(max(retention_days, 1), 30)
        config["schema_version"] = CONFIG_SCHEMA_VERSION
        return config

    def _load_password(
        self,
        config: Dict[str, Any],
        disk_config: Mapping[str, Any],
    ) -> bool:
        protected_password = disk_config.get("protected_password")
        if protected_password:
            config["password"] = self.credential_protector.unprotect(str(protected_password))
            return False

        legacy_password = disk_config.get("password")
        if legacy_password and self.legacy_password_decryptor is not None:
            try:
                config["password"] = self.legacy_password_decryptor(str(legacy_password))
            except Exception:
                # 旧密钥无法解密时保留原始文件备份，清空密码并立即重写为新格式，
                # 避免应用无法启动；其余配置项不丢失。
                self._backup_legacy_config()
                config["password"] = ""
            return True

        config["password"] = ""
        return "password" in disk_config

    def _migrate_legacy_location(self) -> None:
        if self.config_path.exists() or self.legacy_config_path is None:
            return
        if not self.legacy_config_path.exists():
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.legacy_config_path, self.config_path)

    def _backup_corrupt_file(self) -> None:
        if not self.config_path.exists():
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.config_path.with_name(f"config.corrupt-{timestamp}.json")
        shutil.move(self.config_path, backup_path)

    def _backup_legacy_config(self) -> None:
        """Copy the raw config before it is rewritten without an undecryptable password."""
        if not self.config_path.exists():
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.config_path.with_name(f"config.legacy-{timestamp}.json")
        shutil.copy2(self.config_path, backup_path)
