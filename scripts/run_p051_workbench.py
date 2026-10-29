"""Launch the approved P05.1 desktop from its dedicated dependency environment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop/p051/src"))
from p051_desktop.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
