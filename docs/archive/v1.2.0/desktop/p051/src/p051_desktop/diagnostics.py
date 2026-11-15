"""Local startup checks and integration with the independently runnable diagnostic kit."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

APP_VERSION = "1.2.0"


def check_startup(
    root, runs, backend="light", isaac=None, powershell=None, *, probe=True, runner=None
):
    root, runs = Path(root), Path(runs)
    portable = (root / "portable-launch.py").is_file()
    checks = []

    def add(key, ok, target, fix, *, optional=False):
        checks.append(
            dict(
                id=key,
                status="PASS" if ok else "WARN" if optional else "FAIL",
                target=str(target),
                fix=fix,
            )
        )

    repair = (
        "完整解压新版 ZIP，保留 EXE 同级 app 目录 / Extract the complete ZIP with its app folder."
        if portable
        else "在项目根目录执行 uv sync --locked；桌面环境另执行 uv sync --locked --project desktop/p051 / Sync both environments from the project root."
    )
    python = root / ".venv/Scripts/python.exe"
    for key, path in (
        ("CPU_PYTHON", python),
        ("WORKER_SCRIPT", root / "scripts/run_s19b_prototype.py"),
        ("GANTT_ASSETS", root / "desktop/p051/web/dist/index.html"),
    ):
        add(key, path.is_file(), path, repair)
    try:
        runs.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=runs) as stream:
            stream.write(b"HRC writable probe")
        add("RESULTS_WRITABLE", True, runs, "")
    except OSError as exc:
        add(
            "RESULTS_WRITABLE",
            False,
            runs,
            f"选择当前用户可写的结果目录 / Choose a writable results folder. ({exc})",
        )
    if backend == "isaac":
        isaac = Path(isaac or "D:/Dev/tools/isaac-sim-6.1")
        version = ""
        try:
            version = (isaac / "VERSION").read_text("utf-8").strip()
        except (OSError, UnicodeError):
            pass
        add(
            "ISAAC_61",
            (isaac / "python.bat").is_file() and version.startswith("6.1."),
            isaac,
            "在环境设置中选择 Isaac Sim 6.1 的安装根目录 / Select the Isaac Sim 6.1 installation.",
        )
        ps = Path(powershell or "C:/Program Files/PowerShell/7/pwsh.exe")
        add(
            "POWERSHELL_7",
            ps.is_file(),
            ps,
            "安装 PowerShell 7；CPU 模式不需要 Isaac / Install PowerShell 7 for Isaac mode.",
        )
        add(
            "KIT_ASCII_RESULTS",
            str(runs).isascii(),
            runs,
            "Kit 结果路径使用英文字母，例如 C:/HRC/runs / Use an ASCII results path for Kit.",
        )
        add(
            "KIT_LAUNCH_SCRIPT",
            (root / "scripts/launch_s19b_kit.ps1").is_file(),
            root / "scripts/launch_s19b_kit.ps1",
            repair,
        )
    if probe and python.is_file():
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONEXE")
        }
        code = (
            "import sys;sys.path[:0]=['src','scripts','.'];"
            "from ortools.sat.python import cp_model;cp_model.CpModel();"
            "from build_simulation_production import configuration;configuration(products=1,variant='SR-W1')"
        )
        try:
            result = (runner.run if runner else subprocess.run)(
                [str(python), "-B", "-X", "utf8", "-c", code],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=40,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            add(
                "CPU_IMPORT",
                result.returncode == 0,
                python,
                repair + ("\n" + result.stderr[-2000:] if result.returncode else ""),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            add("CPU_IMPORT", False, python, repair + "\n" + str(exc))
    return dict(
        format="HRC-STARTUP-CHECK-1",
        version=APP_VERSION,
        backend=backend,
        ready=all(c["status"] != "FAIL" for c in checks),
        checks=checks,
        scope="Startup prerequisites only; does not start production or certify runtime performance.",
    )


def prepare_checked_launch(root, runs, data, isaac=None, powershell=None, runner=None):
    from .client import prepare_launch

    result = check_startup(
        root, runs, data.get("backend", "light"), isaac, powershell, runner=runner
    )
    if not result["ready"]:
        failures = [
            f"{x['id']}: {x['target']}\n{x['fix']}"
            for x in result["checks"]
            if x["status"] == "FAIL"
        ]
        raise ValueError("STARTUP_CHECK_FAILED\n" + "\n\n".join(failures))
    return prepare_launch(root, runs, data)


def full_diagnostics(root, runs, powershell, backend="light", directory=None, runner=None):
    root, runs = Path(root), Path(runs)
    script = root / "tools/diagnostics/Test-HRCWorkbench.ps1"
    if not Path(powershell).is_file():
        return dict(
            ready=False,
            checks=[
                dict(
                    id="POWERSHELL_7",
                    status="FAIL",
                    target=str(powershell),
                    fix="完整自检需要 PowerShell 7。快速启动检查仍可使用 / Full diagnostics require PowerShell 7.",
                )
            ],
        )
    if not script.is_file():
        raise ValueError(f"DIAGNOSTICS_MISSING: {script}")
    parent = runs / ".diagnostics"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="check-", dir=parent))
    package = root.parent if (root / "portable-launch.py").is_file() else root
    command = [
        str(powershell),
        "-NoProfile",
        "-File",
        str(script),
        "-Root",
        str(package),
        "-Backend",
        "Isaac" if backend == "isaac" else "CPU",
        "-RunsDirectory",
        str(runs),
        "-OutputDirectory",
        str(output),
    ]
    if directory:
        command += ["-RunDirectory", str(directory)]
    result = (runner.run if runner else subprocess.run)(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    reports = list(output.glob("*/diagnosis.json"))
    if not reports:
        raise ValueError("DIAGNOSTICS_FAILED: " + (result.stderr or result.stdout)[-2000:])
    report = json.loads(reports[0].read_text("utf-8-sig"))
    report.update(
        ready=report["failures"] == 0,
        report_directory=str(reports[0].parent),
        powershell_exit=result.returncode,
    )
    return report
