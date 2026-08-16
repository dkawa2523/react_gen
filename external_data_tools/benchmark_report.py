"""CLI and stable public API for benchmark report generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from external_data_tools.benchmark_evaluation import evaluate_suite
from external_data_tools.benchmark_markdown import render_benchmark_markdown
from external_data_tools.benchmark_report_data import load_benchmark_report_data


def generate_benchmark_report(
    summary_path: str | Path,
    output: str | Path | None = None,
) -> dict[str, Any]:
    summary_file = Path(summary_path)
    summary, cases, setup = load_benchmark_report_data(summary_file)
    evaluation = evaluate_suite(cases, setup)
    markdown = render_benchmark_markdown(summary_file, summary, cases, setup, evaluation)
    output_path = (
        Path(output)
        if output is not None
        else summary_file.with_name("semiconductor_benchmark_report.md")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return {
        "schema_version": 1,
        "summary": summary_file.as_posix(),
        "output": output_path.as_posix(),
        "case_count": len(cases),
        "statuses": evaluation["status_counts"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a human-readable semiconductor benchmark evaluation report."
    )
    parser.add_argument("summary", type=Path, help="benchmarks/results/summary.yaml")
    parser.add_argument("--output", type=Path, default=None, help="Markdown report path")
    args = parser.parse_args(argv)

    result = generate_benchmark_report(args.summary, args.output)
    statuses = result["statuses"]
    print(f"Wrote benchmark evaluation report: {result['output']}")
    print(f"  cases: {result['case_count']}")
    print(f"  passed: {statuses['passed']}")
    print(f"  warnings: {statuses['warning']}")
    print(f"  failed: {statuses['failed']}")
    return 0 if statuses["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
