"""Assemble only the application and its declared portable resources."""

import shutil
import sys
from pathlib import Path

SCRIPTS = (
    "build_building_contracts.py",
    "build_logistics_contracts.py",
    "build_production_contracts.py",
    "build_simulation_production.py",
    "inspect_s19b_scene_supports.py",
    "launch_s19b_kit.ps1",
    "p051_native_telemetry.py",
    "run_s19b_prototype.py",
    "supervise_s19b.py",
)


def copy_tree(source, target):
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "ensurepip"),
    )


def stage(project, destination, python, web):
    app = destination / "app"
    runtime = app / ".venv/Scripts"
    for name in ("DLLs", "Lib"):
        copy_tree(python / name, runtime / name)
    for name in (
        "BUILD",
        "LICENSE.txt",
        "python.exe",
        "python3.dll",
        "python312.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ):
        shutil.copy2(python / name, runtime / name)
    # OR-Tools imports before Qt and needs the app-local MSVC C++ runtime.
    for dll in (runtime / "Lib/site-packages/PySide6").glob("msvcp140*.dll"):
        shutil.copy2(dll, runtime)
    (runtime / "python312._pth").write_text(
        ".\nDLLs\nLib\nLib/site-packages\n../../src\n../../desktop/p051/src\n", encoding="ascii"
    )
    for name in (
        "src/adaptive_hrc_scheduling",
        "sim",
        "desktop/p051/src",
        "desktop/s19b/src",
        "schemas",
    ):
        copy_tree(project / name, app / name)
    files = [
        "desktop/s19b/pyproject.toml",
        "desktop/s19b/uv.lock",
        "examples/online/limits.json",
        "examples/building_contracts/configuration.json",
        "docs/model/steel_process.tsv",
        "docs/model/steel_edges.tsv",
        *[f"scripts/{name}" for name in SCRIPTS],
    ]
    for name in files:
        target = app / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / name, target)

    portable = project / "desktop/p051/portable"
    shutil.copy2(portable / "portable-launch.py", app)
    shutil.copy2(project / "LICENSE", destination / "LICENSE.txt")
    for name in ("START-HERE.md", "THIRD-PARTY.md", "WorkbenchLauncher.cs"):
        shutil.copy2(portable / name, destination)
    copy_tree(portable / "licenses", destination / "licenses/qt")
    for name in ("index.html", "package.json", "package-lock.json", "vite.config.js"):
        shutil.copy2(project / "desktop/p051/web" / name, web)
    for name in ("src", "tests"):
        copy_tree(project / "desktop/p051/web" / name, web / name)
    copy_tree(web / "src", app / "desktop/p051/web/src")
    for name in ("index.html", "package.json", "package-lock.json", "vite.config.js"):
        shutil.copy2(web / name, app / "desktop/p051/web")


def web_notices(web, destination):
    target = destination / "licenses/web"
    target.mkdir(parents=True)
    for name in (
        "react",
        "react-dom",
        "scheduler",
        "@tanstack/react-virtual",
        "@tanstack/virtual-core",
    ):
        module = web / "node_modules" / name
        notice = next(path for path in module.iterdir() if path.name.lower().startswith("license"))
        shutil.copy2(notice, target / (name.replace("@", "").replace("/", "-") + ".txt"))


if __name__ == "__main__":
    if sys.argv[1] == "--web-notices":
        web_notices(*map(Path, sys.argv[2:]))
    else:
        stage(*map(Path, sys.argv[1:]))
