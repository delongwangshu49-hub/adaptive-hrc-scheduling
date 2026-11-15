"""Owned, cancellable read-only helper processes; never controls production workers."""

import os
import subprocess
import threading
from pathlib import Path


class CancellableProcesses:
    def __init__(self):
        self.lock = threading.Lock()
        self.children = set()
        self.closed = False

    def run(self, args, *, input=None, timeout=None, capture_output=False, **kwargs):
        if capture_output:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if input is not None:
            kwargs["stdin"] = subprocess.PIPE
        with self.lock:
            if self.closed:
                raise RuntimeError("READ_ONLY_CHECK_CANCELLED")
            child = subprocess.Popen(args, **kwargs)
            self.children.add(child)
        try:
            try:
                stdout, stderr = child.communicate(input, timeout=timeout)
            except subprocess.TimeoutExpired:
                self.stop(child)
                child.communicate()
                raise
            if self.closed:
                raise RuntimeError("READ_ONLY_CHECK_CANCELLED")
            return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
        finally:
            with self.lock:
                self.children.discard(child)

    @staticmethod
    def stop(child):
        if child.poll() is not None:
            return
        if os.name == "nt":
            # The handle remains owned and live: only this check's process tree is targeted.
            taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"
            try:
                subprocess.run(
                    [str(taskkill), "/PID", str(child.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if child.poll() is None:
            child.kill()

    def close(self):
        with self.lock:
            self.closed = True
            children = list(self.children)
        for child in children:
            self.stop(child)
