from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skillra_pda.trend_readiness import (  # noqa: E402
    DEFAULT_MIN_FORWARD_WEEKS,
    build_trend_readiness_report,
    load_processed_run_evidence,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Skillra trend-readiness report from processed dataset run metadata.",
    )
    parser.add_argument(
        "--processed-runs-dir",
        type=Path,
        default=Path("data") / "processed" / "runs",
        help="Directory containing processed runs/<run_id>/dataset_meta.json.",
    )
    parser.add_argument(
        "--min-forward-weeks",
        type=int,
        default=DEFAULT_MIN_FORWARD_WEEKS,
        help="Minimum complete generated weeks required for forward-built review.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument(
        "--require-public-blocked",
        action="store_true",
        help="Fail if the report says public trend claims are currently allowed.",
    )
    return parser.parse_args()


def write_or_print(payload: dict, output: Path | None) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output is None:
        print(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")
    print(f"Wrote {output}")


def main() -> None:
    args = parse_args()
    evidence = load_processed_run_evidence(args.processed_runs_dir)
    report = build_trend_readiness_report(evidence, min_forward_weeks=args.min_forward_weeks)
    write_or_print(report, args.output)
    if args.require_public_blocked and report["public_trends_allowed"]:
        raise SystemExit("Public trend claims are allowed by report; expected blocked state.")


if __name__ == "__main__":
    main()
