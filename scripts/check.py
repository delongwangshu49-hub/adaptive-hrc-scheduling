"""Run the same lightweight checks locally and in CI; stop on any failure."""

import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    expected = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    if platform.python_version() != expected:
        raise SystemExit(f"Expected Python {expected}; got {platform.python_version()}")

    run("uv", "lock", "--check")
    run(sys.executable, "-m", "ruff", "check", "src", "tests", "scripts", "sim")
    run(sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts", "sim")
    run(sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests", "-v")
    run("uv", "pip", "check", "--python", sys.executable)

    # Each invocation owns a fresh temporary directory; no shared build outputs.
    with tempfile.TemporaryDirectory(prefix="hrc-check-") as temporary:
        directory = Path(temporary)
        artifacts = directory / "dist"
        run("uv", "build", "--no-sources", "--no-cache", "--out-dir", str(artifacts))
        wheels = list(artifacts.glob("*.whl"))
        if len(wheels) != 1 or len(list(artifacts.glob("*.tar.gz"))) != 1:
            raise SystemExit("Expected exactly one wheel and one source distribution")
        environment = directory / "wheel-env"
        run("uv", "venv", "--python", sys.executable, str(environment))
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        requirements = directory / "reference-requirements.txt"
        run(
            "uv",
            "export",
            "--locked",
            "--only-group",
            "reference",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
        )
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--link-mode",
            "copy",
            "-r",
            str(requirements),
        )
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--no-cache",
            "--link-mode",
            "copy",
            str(wheels[0]),
        )
        run(str(python), "-I", "-m", "unittest", "discover", "-s", "tests", "-v")
        run("uv", "pip", "check", "--python", str(python))
    print("All local CPU checks passed. Remote CI and simulation are separate validations.")


if __name__ == "__main__":
    main()
