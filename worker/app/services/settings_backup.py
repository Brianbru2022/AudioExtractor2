from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.repositories.meetings import SettingsRepository


class SettingsBackupService:
    def __init__(self, settings_repository: SettingsRepository, backup_path: Path) -> None:
        self.settings_repository = settings_repository
        self.backup_path = backup_path
        self.backup_keys = {"transcription_defaults", "gemini_defaults"}

    def restore_cloud_settings_if_missing(self) -> None:
        backup = self._read_backup()
        if not backup:
            return

        existing_records = {row["key"]: row.get("value_json", {}) for row in self.settings_repository.list()}
        restored_any = False
        for key in self.backup_keys:
            if key in backup and self._should_restore(key, existing_records.get(key)):
                self.settings_repository.upsert(key, backup[key])
                restored_any = True

        if restored_any:
            self._write_backup({key: backup[key] for key in self.backup_keys if key in backup})

    def upsert(self, key: str, value_json: dict[str, Any]) -> dict[str, Any]:
        record = self.settings_repository.upsert(key, value_json)
        if key in self.backup_keys:
            backup = self._read_backup()
            backup[key] = value_json
            self._write_backup(backup)
        return record

    def _read_backup(self) -> dict[str, dict[str, Any]]:
        if not self.backup_path.exists():
            return {}
        try:
            payload = json.loads(self.backup_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        settings = payload.get("settings") if isinstance(payload, dict) else None
        return settings if isinstance(settings, dict) else {}

    def _write_backup(self, settings: dict[str, dict[str, Any]]) -> None:
        self.backup_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"settings": settings}
        self.backup_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _should_restore(self, key: str, current_value: dict[str, Any] | None) -> bool:
        if not current_value:
            return True

        if key == "transcription_defaults":
            project_id = str(current_value.get("project_id", "")).strip()
            staging_bucket = str(current_value.get("staging_bucket", "")).strip()
            credentials_path = str(current_value.get("credentials_path", "")).strip()
            auth_mode = str(current_value.get("auth_mode", "")).strip()
            return not project_id or not staging_bucket or (auth_mode == "credentials_file" and not credentials_path)

        if key == "gemini_defaults":
            auth_mode = str(current_value.get("auth_mode", "")).strip()
            api_key_file_path = str(current_value.get("api_key_file_path", "")).strip()
            api_key_env_var = str(current_value.get("api_key_env_var", "")).strip()
            if auth_mode == "api_key_file":
                return not api_key_file_path
            if auth_mode == "api_key_env":
                return not api_key_env_var
            return not auth_mode

        return False
