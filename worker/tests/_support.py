from __future__ import annotations

import importlib
import os
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


class IsolatedWorkerApp:
    def __init__(self, *, prefix: str) -> None:
        self.prefix = prefix
        self.root: Path | None = None
        self.client: TestClient | None = None
        self.app = None
        self.services = None
        self._previous_storage_root = os.environ.get("AUDIO_EXTRACTOR_STORAGE_ROOT")
        self._previous_settings_backup_path = os.environ.get("AUDIO_EXTRACTOR_SETTINGS_BACKUP_PATH")

    def start(self) -> "IsolatedWorkerApp":
        self.root = Path(tempfile.mkdtemp(prefix=self.prefix))
        os.environ["AUDIO_EXTRACTOR_STORAGE_ROOT"] = str(self.root / "storage")
        os.environ["AUDIO_EXTRACTOR_SETTINGS_BACKUP_PATH"] = str(self.root / "cloud_settings.json")

        import app.core.config as config_module
        import app.main as main_module

        importlib.reload(config_module)
        main_module = importlib.reload(main_module)

        self.app = main_module.app
        self.client = TestClient(self.app)
        self.services = self.app.state.services
        return self

    def stop(self) -> None:
        if self.client is not None:
            self.client.close()

        if self._previous_storage_root is None:
            os.environ.pop("AUDIO_EXTRACTOR_STORAGE_ROOT", None)
        else:
            os.environ["AUDIO_EXTRACTOR_STORAGE_ROOT"] = self._previous_storage_root

        if self._previous_settings_backup_path is None:
            os.environ.pop("AUDIO_EXTRACTOR_SETTINGS_BACKUP_PATH", None)
        else:
            os.environ["AUDIO_EXTRACTOR_SETTINGS_BACKUP_PATH"] = self._previous_settings_backup_path

        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
