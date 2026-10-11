"""Export a review copy with content-addressed local texture dependencies."""

import hashlib
import shutil
from pathlib import Path

from pxr import Sdf, Usd


def export_review_stage(stage, destination):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Author portability only on a flattened copy; never mutate the live scene.
    layer = stage.Flatten()
    copy = Usd.Stage.Open(layer)
    dependencies = []
    for prim in copy.Traverse():
        for attribute in prim.GetAttributes():
            value = attribute.Get()
            if not isinstance(value, Sdf.AssetPath) or not value.path:
                continue
            source = Path(value.resolvedPath or value.path)
            if not source.is_file():
                raise ValueError("REVIEW_ASSET_UNRESOLVED:" + str(prim.GetPath()))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            relative = Path("_assets") / (digest[:16] + "-" + source.name)
            target = destination.parent / relative
            target.parent.mkdir(exist_ok=True)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError("REVIEW_ASSET_COPY_DRIFT")
            else:
                shutil.copyfile(source, target)
            attribute.Set(Sdf.AssetPath(relative.as_posix()))
            dependencies.append({"file": relative.as_posix(), "sha256": digest})
    if not layer.Export(str(destination)):
        raise ValueError("REVIEW_EXPORT_FAILED")
    return dependencies
