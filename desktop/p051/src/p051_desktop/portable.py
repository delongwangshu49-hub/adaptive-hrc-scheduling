"""User-local configuration for the directory distribution."""

import os
from pathlib import Path

from s19b_desktop.model import atomic_json, read_json

POWERSHELL = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PowerShell/7/pwsh.exe"


def user_data():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "HRCWorkbench"


class PortableSettings:
    def __init__(self, root):
        self.data = user_data()
        self.file = self.data / "settings.json"
        self.archive = root / "examples/portable-session"
        self.isaac = None
        self.runs = self.data / "runs"
        self.error = None
        if self.file.exists():
            try:
                stored = read_json(self.file, 64_000)
                if not isinstance(stored, dict):
                    raise ValueError("settings.json")
                isaac = stored.get("isaac")
                if isaac:
                    self.isaac = Path(isaac).resolve(strict=False)
                self.runs = Path(stored.get("runs") or self.runs).resolve(strict=False)
            except (OSError, TypeError, ValueError) as exc:
                self.error = f"无法读取配置 / Could not read settings: {exc}"

    def status(self):
        version = None
        if self.isaac and (self.isaac / "python.bat").is_file():
            try:
                version = (self.isaac / "VERSION").read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                pass
        return dict(
            isaac=str(self.isaac) if self.isaac else None,
            isaac_version=version,
            isaac_ready=bool(version and version.startswith("6.1.") and POWERSHELL.is_file()),
            powershell=POWERSHELL.is_file(),
            runs=str(self.runs),
            archive=(self.archive / "run-spec.json").is_file(),
            error=self.error,
        )

    def save(self, *, isaac, runs):
        self.data.mkdir(parents=True, exist_ok=True)
        atomic_json(self.file, dict(isaac=str(isaac) if isaac else None, runs=str(runs)))
        self.isaac, self.runs, self.error = isaac, runs, None
