"""P051 display telemetry may stay stale when Windows temporarily denies replacement."""

import json
from pathlib import Path

from s19b_desktop.model import atomic_json


class NativeFramePublisher:
    """Publish only native-frame telemetry; never handle transactions or session saves."""

    def __init__(self, directory):
        self.path = Path(directory) / "p051-native-frame.json"
        self.skipped = 0

    def publish(self, frame):
        try:
            atomic_json(self.path, frame)
        except PermissionError as error:
            self.skipped += 1
            if self.skipped == 1:
                print(
                    json.dumps(
                        dict(
                            kind="P051_NATIVE_FRAME_PUBLICATION_DEFERRED",
                            scope="DISPLAY_ONLY_PREVIOUS_TIMESTAMP_RETAINED",
                            run_id=frame["run_id"],
                            error=str(error),
                        )
                    ),
                    flush=True,
                )
            return False
        if self.skipped:
            print(
                json.dumps(
                    dict(
                        kind="P051_NATIVE_FRAME_PUBLICATION_RECOVERED",
                        run_id=frame["run_id"],
                        skipped_updates=self.skipped,
                    )
                ),
                flush=True,
            )
            self.skipped = 0
        return True
