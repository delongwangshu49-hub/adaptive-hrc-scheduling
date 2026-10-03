"""Generate the complete scene-only R5 world-coordinate transfer matrix."""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from sim.isaac.scene.target_layout import transfer_matrix

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows = transfer_matrix()
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: json.dumps(v, separators=(",", ":")) if isinstance(v, (tuple, list, dict)) else v
                for k, v in row.items()
            }
        )
    target = ROOT / "docs/sim/S13_transfer_coverage.tsv"
    if args.check:
        if target.read_text(encoding="utf-8") != buf.getvalue():
            raise SystemExit("Transfer matrix differs from the checked source")
    else:
        target.write_text(buf.getvalue(), encoding="utf-8", newline="\n")
    print(f"{len(rows)} task/empty/tool-cart routes checked; scene geometry only.")


if __name__ == "__main__":
    main()
