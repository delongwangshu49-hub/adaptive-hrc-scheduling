"""Bootstrap the same desktop entry point with a user-local startup log."""

import ctypes
import os
import sys
import traceback
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "HRCWorkbench"
    log_path = data / "startup.log"
    try:
        data.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            original_streams = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = log
            try:
                print(f"HRC Workbench launch (PID {os.getpid()})")
                if not (root / "desktop/p051/web/dist/index.html").is_file():
                    raise FileNotFoundError("Packaged Gantt assets are missing")
                from ortools.sat.python import cp_model

                cp_model.CpModel()
                from p051_desktop.app import main as desktop_main

                return desktop_main()
            except Exception:
                traceback.print_exc()
                raise
            finally:
                sys.stdout, sys.stderr = original_streams
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"工作台启动失败 / Workbench startup failed\n{error}\n\n{log_path}",
            "HRC Workbench",
            0x10,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
