"""Validate and add a new report without replacing an existing report source."""
import argparse
import json
from pathlib import Path

from build_site import ROOT, validate


def add_report(source: Path, data_dir: Path = ROOT / "data/reports") -> Path:
    report = json.loads(source.read_text(encoding="utf-8"))
    validate(report)
    target = data_dir / (report["id"] + ".json")
    data_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive creation is only a local guarantee. Remote concurrent writers must
    # also use ordinary Git fast-forward checks; never force push.
    with target.open("x", encoding="utf-8") as file:
        file.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(add_report(args.source))
