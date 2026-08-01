import json
import unittest.mock
from datetime import datetime
from pathlib import Path

from srunpy.config import CONFIG_SCHEMA_VERSION, ConfigStore


class ReversibleTestProtector:
    """Deterministic test double; production uses current-user Windows DPAPI."""

    def protect(self, plaintext: str) -> str:
        return f"protected::{plaintext[::-1]}"

    def unprotect(self, protected_value: str) -> str:
        prefix = "protected::"
        if not protected_value.startswith(prefix):
            raise ValueError("invalid protected test value")
        return protected_value[len(prefix):][::-1]


def create_store(config_path: Path, **kwargs: object) -> ConfigStore:
    return ConfigStore(config_path, ReversibleTestProtector(), **kwargs)


def test_save_does_not_mutate_config_or_store_plaintext_password(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = create_store(config_path)
    config = {"username": "student", "password": "secret"}

    store.save(config)

    assert config["password"] == "secret"
    disk_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "password" not in disk_config
    assert disk_config["protected_password"] == "protected::terces"
    assert disk_config["schema_version"] == CONFIG_SCHEMA_VERSION


def test_load_recovers_password_and_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    store = create_store(config_path)
    store.save({"username": "student", "password": "secret"})

    config = store.load()

    assert config["username"] == "student"
    assert config["password"] == "secret"
    assert config["local_ips"] == [None]


def test_legacy_password_is_migrated_to_protected_storage(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"username": "student", "password": "legacy-ciphertext"}),
        encoding="utf-8",
    )
    store = create_store(
        config_path,
        legacy_password_decryptor=lambda ciphertext: f"decoded::{ciphertext}",
    )

    config = store.load()

    assert config["password"] == "decoded::legacy-ciphertext"
    migrated_disk_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "password" not in migrated_disk_config
    assert migrated_disk_config["protected_password"].startswith("protected::")


def test_corrupt_config_is_backed_up_before_defaults_are_restored(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{not valid json", encoding="utf-8")
    store = create_store(config_path)

    config = store.load()

    assert config["schema_version"] == CONFIG_SCHEMA_VERSION
    assert config_path.exists()
    backups = list(tmp_path.glob("config.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"


def test_legacy_roaming_location_is_copied_once(tmp_path: Path) -> None:
    current_path = tmp_path / "local" / "config.json"
    legacy_path = tmp_path / "roaming" / "config.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        json.dumps({"username": "student", "password": ""}),
        encoding="utf-8",
    )
    store = create_store(current_path, legacy_config_path=legacy_path)

    config = store.load()

    assert config["username"] == "student"
    assert current_path.exists()
    assert legacy_path.exists()


def test_traffic_preferences_are_normalized_to_safe_bounds(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "traffic_sampling_enabled": 0,
                "traffic_sample_interval": "100",
                "traffic_history_enabled": 1,
                "traffic_retention_days": -10,
            }
        ),
        encoding="utf-8",
    )

    config = create_store(config_path).load()

    assert config["traffic_sampling_enabled"] is False
    assert config["traffic_sample_interval"] == 5.0
    assert config["traffic_history_enabled"] is True
    assert config["traffic_retention_days"] == 1


def test_misc_fields_are_normalized_to_safe_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "sleeptime": "abc",
                "srun_host": "  ",
                "host_ip": None,
                "self_service": " zfw.example.edu ",
                "local_ips": ["10.0.0.2", "not-an-ip", None, 123, "10.0.0.2", "null"],
                "active_ip": "192.168.1.99",
            }
        ),
        encoding="utf-8",
    )

    config = create_store(config_path).load()

    assert config["sleeptime"] == 5
    assert config["srun_host"] == "gw.buaa.edu.cn"
    assert config["host_ip"] == "gw.buaa.edu.cn"
    assert config["self_service"] == "zfw.example.edu"
    assert config["local_ips"] == ["10.0.0.2", None]
    assert config["active_ip"] == "10.0.0.2"


def test_sleeptime_and_ip_selection_are_clamped(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "sleeptime": 1000,
                "local_ips": [],
                "active_ip": "10.0.0.1",
            }
        ),
        encoding="utf-8",
    )

    config = create_store(config_path).load()

    assert config["sleeptime"] == 300
    assert config["local_ips"] == [None]
    assert config["active_ip"] is None


def test_undecryptable_legacy_password_is_backed_up_and_cleared(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"username": "student", "password": "legacy-ciphertext"}),
        encoding="utf-8",
    )

    def broken_decryptor(_: str) -> str:
        raise ValueError("wrong legacy key")

    store = create_store(config_path, legacy_password_decryptor=broken_decryptor)

    config = store.load()

    assert config["username"] == "student"
    assert config["password"] == ""
    backups = list(tmp_path.glob("config.legacy-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["password"] == (
        "legacy-ciphertext"
    )
    disk_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "password" not in disk_config
    assert disk_config["protected_password"] == ""


class FailingProtector:
    """Test double whose unprotect always fails (simulates corrupt/cross-user DPAPI)."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.protected_seen = []

    def protect(self, plaintext: str) -> str:
        return f"protected::{plaintext}"

    def unprotect(self, protected_value: str) -> str:
        self.protected_seen.append(protected_value)
        raise self._error


def test_undecryptable_dpapi_credential_is_backed_up_and_cleared(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "username": "student",
                "protected_password": "AAAA-not-valid-base64!!",
                "pass_correct": True,
                "auto_login": True,
                "sleeptime": 5,
            }
        ),
        encoding="utf-8",
    )
    protector = FailingProtector(ValueError("corrupt protected value"))
    store = ConfigStore(config_path, protector)

    config = store.load()

    # Other settings are preserved.
    assert config["username"] == "student"
    assert config["sleeptime"] == 5
    # Credential is cleared and auto-login is disabled so the app can start.
    assert config["password"] == ""
    assert config["pass_correct"] is False
    assert config["auto_login"] is False
    # The original encrypted blob was the failing value.
    assert protector.protected_seen == ["AAAA-not-valid-base64!!"]

    backups = list(tmp_path.glob("config.credential-*.json"))
    assert len(backups) == 1
    backup_data = json.loads(backups[0].read_text(encoding="utf-8"))
    assert backup_data["protected_password"] == "AAAA-not-valid-base64!!"
    # No plaintext password is ever written to disk.
    disk_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "password" not in disk_config
    assert disk_config["protected_password"] == ""


def test_cross_user_dpapi_credential_recovers_without_plaintext(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "username": "student",
                "protected_password": "encrypted-for-another-user",
                "pass_correct": True,
                "auto_login": True,
            }
        ),
        encoding="utf-8",
    )
    protector = FailingProtector(RuntimeError("wrong user scope"))
    store = ConfigStore(config_path, protector)

    config = store.load()

    assert config["password"] == ""
    assert config["auto_login"] is False
    disk_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "password" not in disk_config
    assert disk_config["protected_password"] == ""


def test_credential_backup_does_not_collide_on_same_second(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    # Pre-existing backup that would collide with the new timestamp-based name.
    collide = tmp_path / "config.credential-20200101-000000.json"
    collide.write_text("occupied", encoding="utf-8")

    config_path.write_text(
        json.dumps({"username": "student", "protected_password": "bad"}),
        encoding="utf-8",
    )
    store = ConfigStore(config_path, FailingProtector(ValueError("boom")))
    with unittest.mock.patch("srunpy.config.datetime") as fake_datetime:
        fake_datetime.now.return_value = datetime(2020, 1, 1, 0, 0, 0)
        store.load()

    backups = sorted(tmp_path.glob("config.credential-*.json"))
    assert len(backups) == 2
    assert collide.read_text(encoding="utf-8") == "occupied"
    # The new backup used the collision-free suffix rather than overwriting.
    assert {b.name for b in backups} == {
        "config.credential-20200101-000000.json",
        "config.credential-20200101-000000-1.json",
    }
