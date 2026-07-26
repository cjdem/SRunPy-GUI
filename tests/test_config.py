import json
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
