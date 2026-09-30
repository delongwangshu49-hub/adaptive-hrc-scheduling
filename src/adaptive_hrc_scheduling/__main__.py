"""Report installation metadata without starting a simulation."""

import json
import platform
from importlib.metadata import version


def main() -> None:
    print(
        json.dumps(
            {
                "package": "adaptive-hrc-scheduling",
                "version": version("adaptive-hrc-scheduling"),
                "python": platform.python_version(),
                "scope": "installation-only",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
