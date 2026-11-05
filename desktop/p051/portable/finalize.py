"""Add a verified CPU archive and produce a byte-verified delivery ZIP."""

import hashlib
import json
import shutil
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def sha256(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def install_archive(package, source):
    if (source / "session/run-spec.json").is_file():
        source /= "session"
    spec = json.loads((source / "run-spec.json").read_bytes())
    if spec["backend"] != "CPU":
        raise ValueError("The portable example must be a CPU archive")
    target = package / "app/examples/portable-session"
    target.mkdir(parents=True)
    for name in ("run-spec.json", "timeline.jsonl", "final-commit.json"):
        shutil.copy2(source / name, target)
    for name in ("full-schedules", "gantt-schedules"):
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name)


def pack(package):
    zip_path = package.with_suffix(".zip")
    manifest = package / "PACKAGE-SHA256.txt"
    files = sorted(path for path in package.rglob("*") if path.is_file())
    console_wrappers = package / "app/.venv/Scripts/Lib/site-packages/bin"
    files = [
        path
        for path in files
        if path != manifest
        and "__pycache__" not in path.parts
        and not path.is_relative_to(console_wrappers)
    ]
    expected = {}
    for path in files:
        with path.open("rb") as stream:
            expected[path.relative_to(package).as_posix()] = sha256(stream)
    manifest.write_text(
        "".join(f"{value}  {name}\n" for name, value in expected.items()), encoding="utf-8"
    )
    with manifest.open("rb") as stream:
        expected[manifest.name] = sha256(stream)
    with ZipFile(zip_path, "x", ZIP_DEFLATED, compresslevel=4) as archive:
        for path in (*files, manifest):
            archive.write(path, path.relative_to(package.parent).as_posix())
    with ZipFile(zip_path) as archive:
        names = [f"{package.name}/{name}" for name in expected]
        if sorted(archive.namelist()) != sorted(names):
            raise ValueError("ZIP inventory mismatch")
        for name, digest in zip(names, expected.values(), strict=True):
            with archive.open(name) as stream:
                if sha256(stream) != digest:
                    raise ValueError(f"ZIP content mismatch: {name}")
    with zip_path.open("rb") as stream:
        receipt = dict(
            zip=zip_path.name,
            files=len(expected),
            bytes=zip_path.stat().st_size,
            sha256=sha256(stream),
        )
    zip_path.with_suffix(".zip.sha256").write_text(
        f"{receipt['sha256']}  {zip_path.name}\n", encoding="ascii"
    )
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    package, source = map(Path, sys.argv[1:])
    install_archive(package, source)
    pack(package)
