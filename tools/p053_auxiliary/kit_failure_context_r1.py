"""Identity-bound incomplete-value capture; no Kit imports, writes or audit claims."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class CaptureUnavailable(ValueError):
    """The current row has no safely attributable snapshot."""


@dataclass(frozen=True)
class Capture:
    unit: str
    run_id: str
    epoch: int
    directory: Path
    configuration: object
    snapshot: object
    scene: object
    initial_configuration_sha256: str
    actual_configuration_sha256: str


class KitFailureContext:
    def __init__(self, unit, run_id, epoch, directory, configuration, digest: Callable):
        self.unit = unit
        self.run_id = run_id
        self.epoch = epoch
        self.directory = Path(directory)
        self.initial_configuration_sha256 = digest(configuration)
        self.digest = digest
        self.backend = None
        self.scene = None

    def capture(self):
        if self.backend is None or self.scene is None:
            raise CaptureUnavailable("CURRENT_ROW_NOT_INITIALIZED")
        world = self.backend.world
        port = self.backend.port
        if (world.run_id, world.epoch) != (self.run_id, self.epoch):
            raise CaptureUnavailable("CURRENT_ROW_WORLD_IDENTITY_MISMATCH")
        if (port.run_id, port.epoch) != (self.run_id, self.epoch):
            raise CaptureUnavailable("CURRENT_ROW_PORT_IDENTITY_MISMATCH")
        if port.scene is not self.scene:
            raise CaptureUnavailable("CURRENT_ROW_SCENE_CONTEXT_MISMATCH")
        # A U row may have registered a new product. Save that actual configuration,
        # never the initial C0 beside a snapshot of its generated catalog.
        configuration = world.config
        actual_digest = self.digest(configuration)
        snapshot = world.snapshot()
        if (snapshot.run_id, snapshot.epoch) != (self.run_id, self.epoch):
            raise CaptureUnavailable("CURRENT_ROW_SNAPSHOT_IDENTITY_MISMATCH")
        if (snapshot.config_id, snapshot.schema_version, snapshot.config_sha256) != (
            configuration.id,
            configuration.schema_version,
            actual_digest,
        ):
            raise CaptureUnavailable("CURRENT_ROW_SNAPSHOT_CONFIGURATION_MISMATCH")
        return Capture(
            self.unit,
            self.run_id,
            self.epoch,
            self.directory,
            configuration,
            snapshot,
            self.scene,
            self.initial_configuration_sha256,
            actual_digest,
        )
