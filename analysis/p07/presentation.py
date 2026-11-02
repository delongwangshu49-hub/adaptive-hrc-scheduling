"""Rebuild the current question-led tables and figures without new production."""

import argparse
import json
import os
from pathlib import Path

from load import ROOT
from presentation_data import build_tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "replay"))
    parser.add_argument("--data", type=Path, default=ROOT / "results/p07/r3")
    parser.add_argument("--tables", type=Path, default=ROOT / "results/p07/presentation-r1")
    parser.add_argument("--figures", type=Path, default=ROOT / "figures/p07/r4")
    parser.add_argument("--inputs", type=Path, default=ROOT / "examples/reproduction/p07/r3")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/p07-current-demo")
    args = parser.parse_args()
    if args.action == "replay":
        from reproduce import replay

        args.output = args.output.resolve()
        replay(args.inputs, args.output, figures=False)
        source = args.output
        tables = args.output / "presentation"
        figures = args.output / "figures"
        os.environ["MPLCONFIGDIR"] = str(args.output / "matplotlib-cache")
    else:
        source, tables, figures = args.data, args.tables, args.figures
        os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".local/p07-presentation-cache"))
    build_tables(source, tables)
    from presentation_figures import build_figures

    build_figures(tables, figures)
    print(
        json.dumps(dict(status="CURRENT_PRESENTATION_PASS", new_production=0, new_kit=0, figures=4))
    )


if __name__ == "__main__":
    main()
