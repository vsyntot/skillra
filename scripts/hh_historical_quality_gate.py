from __future__ import annotations

"""Evaluate HH historical backfill control-plane quality gates."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from skillra_pda.ingest.historical_backfill_control import JsonBackfillStore  # noqa: E402
from skillra_pda.ingest.historical_quality import (  # noqa: E402
    HistoricalQualityThresholds,
    evaluate_historical_candidate,
    read_csv_rows,
)

DEFAULT_CONTROL_DIR = Path("data") / "raw" / "hh" / "historical_control"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-dir", type=Path, default=DEFAULT_CONTROL_DIR)
    parser.add_argument("--backfill-id", required=True)
    parser.add_argument("--candidate-csv", type=Path, default=None)
    parser.add_argument("--output-report", type=Path, default=None)
    parser.add_argument("--max-found-per-shard", type=int, default=1_800)
    parser.add_argument("--max-pages-per-shard", type=int, default=18)
    parser.add_argument("--max-duplicate-share", type=float, default=0.05)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = JsonBackfillStore(args.control_dir)
    job, shards = store.load_snapshot(args.backfill_id)
    rows = read_csv_rows(args.candidate_csv) if args.candidate_csv is not None else None
    result = evaluate_historical_candidate(
        job,
        shards,
        rows=rows,
        thresholds=HistoricalQualityThresholds(
            max_found_per_shard=args.max_found_per_shard,
            max_pages_per_shard=args.max_pages_per_shard,
            max_duplicate_share=args.max_duplicate_share,
        ),
    )
    payload: dict[str, Any] = {
        "backfill_id": args.backfill_id,
        "control_dir": str(args.control_dir),
        "candidate_csv": str(args.candidate_csv) if args.candidate_csv else None,
        "quality_gate": result.to_dict(),
    }
    output_report = args.output_report or args.control_dir / args.backfill_id / "quality_gate_report.json"
    write_json(output_report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and result.status != "accepted":
        raise SystemExit(1)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    main()
