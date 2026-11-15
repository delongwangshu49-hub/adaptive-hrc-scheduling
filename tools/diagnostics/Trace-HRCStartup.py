"""Run the existing UI entry and record failed Popen calls without editing the app."""

import datetime
import json
import os
import runpy
import subprocess
import sys
import traceback
from pathlib import Path

root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
log = Path(sys.argv[3]).resolve()
if mode not in ("portable", "source"):
    raise ValueError("mode must be portable or source")
entry = root / ("portable-launch.py" if mode == "portable" else "scripts/run_p051_workbench.py")
if not entry.is_file():
    raise FileNotFoundError(str(entry))
log.parent.mkdir(parents=True, exist_ok=True)
original_popen = subprocess.Popen


class LoggedPopen(original_popen):
    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except OSError:
            record = {
                "time": datetime.datetime.now().astimezone().isoformat(),
                "command": args[0] if args else kwargs.get("args"),
                "cwd": str(kwargs.get("cwd") or os.getcwd()),
                "traceback": traceback.format_exc(),
            }
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            raise


subprocess.Popen = LoggedPopen
os.chdir(root)
sys.path.insert(0, str(entry.parent))
sys.argv = [str(entry)]
runpy.run_path(str(entry), run_name="__main__")
