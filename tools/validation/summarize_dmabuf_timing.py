#!/usr/bin/env python3
"""Summarize the diagnostic player's timing TSV; not display acceptance."""
import argparse
import csv
import json
import statistics
from pathlib import Path


def summarize(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise ValueError("empty frame timing file")
    stages = {}
    for label, start, end in (
        ("fence_and_pull", "begin_ns", "pulled_ns"),
        ("import", "pulled_ns", "imported_ns"),
        ("draw", "imported_ns", "drawn_ns"),
        ("deadline_lateness", "deadline_ns", "swap_begin_ns"),
        ("trace_and_swap", "swap_begin_ns", "swap_end_ns"),
    ):
        values = sorted((int(row[end]) - int(row[start])) / 1e6 for row in rows)
        stages[label] = {
            "mean_ms": statistics.mean(values),
            **{f"p{q}_ms": values[(len(values) - 1) * q // 100] for q in (50, 95, 99)},
            "max_ms": values[-1],
            "over_10ms": sum(value > 10 for value in values),
        }
    return {"file": Path(path).name, "frames": len(rows), "stages": stages,
            "scope": "CPU stage durations; use wp_presentation for displayed frames"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timing", nargs="+")
    args = parser.parse_args()
    print(json.dumps([summarize(path) for path in args.timing], indent=2))
