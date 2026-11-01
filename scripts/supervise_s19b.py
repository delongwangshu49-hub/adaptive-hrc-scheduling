"""Capture the native worker exit before the vendor batch can mask its code."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

WORKER = Path(__file__).with_name("run_s19b_prototype.py")


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def supervise(request_file, launch_id):
    request_file = Path(request_file).resolve()
    payload = request_file.read_bytes()
    request = json.loads(payload)
    identity = dict(
        run_id=request["run_id"],
        request_id=request["request_id"],
        launch_id=launch_id,
        request_sha256=hashlib.sha256(payload).hexdigest(),
    )
    marker = json.loads((request_file.parent / "worker-launch.json").read_bytes())
    if marker.get("format") != "S19B-NATIVE-LAUNCH-1" or any(
        marker.get(key) != value for key, value in identity.items()
    ):
        raise ValueError("NATIVE_LAUNCH_IDENTITY")
    receipt = request_file.parent / "worker-native-exit.json"
    record = dict(
        identity,
        format="S19B-NATIVE-EXIT-1",
        supervisor_pid=os.getpid(),
        command=[sys.executable, "-u", str(WORKER), "--request", str(request_file)],
        state="STARTING",
        returncode=None,
        started_wall_s=time.time(),
    )
    started = time.monotonic()
    atomic_json(receipt, record)
    try:
        worker = subprocess.Popen(
            record["command"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        record.update(state="RUNNING", pid=worker.pid)
        try:
            atomic_json(receipt, record)
        finally:
            # A receipt I/O failure must not abandon an already-started worker.
            code = worker.wait()
        record.update(
            state="EXITED",
            returncode=code,
            windows_code_hex=hex(code & 0xFFFFFFFF),
            elapsed_s=time.monotonic() - started,
        )
        atomic_json(receipt, record)
        return 0 if code == 0 else 1
    except Exception as error:
        record.update(state="UNKNOWN", error=repr(error), elapsed_s=time.monotonic() - started)
        atomic_json(receipt, record)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--launch-id", required=True)
    args = parser.parse_args()
    raise SystemExit(supervise(args.request, args.launch_id))
