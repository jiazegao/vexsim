"""``vexsim bench``."""

from __future__ import annotations

import argparse

from vexsim.cli.common import EXIT_INVALID, EXIT_OK, _print_issues


def cmd_bench(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.bench.runner import run_bench
    from vexsim.bench.scenario import validate_scenario

    report = validate_scenario(args.scenario)
    if not report.ok:
        print(f"Scenario  {report.source}")
        _print_issues(report.issues)
        return EXIT_INVALID

    def names(text: str | None) -> list[str] | None:
        return [n.strip() for n in text.split(",") if n.strip()] if text else None

    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    step = max(1, args.seeds // 10)
    last = [0]

    def progress(done: int, total: int) -> None:
        if done == total or done - last[0] >= step * max(1, total // args.seeds):
            last[0] = done
            print(f"  {done}/{total} trials", flush=True)

    try:
        result = run_bench(
            args.scenario,
            seeds,
            localizers=names(args.localizers),
            controllers=names(args.controllers),
            workers=args.workers,
            progress=progress,
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(
        f"\n{result.loaded.scenario.name}: {len(result.rows)} trials in {result.wall_time_s:.0f} s"
    )
    width = max(len(f"{e['localizer']} / {e['controller']}") for e in result.summary())
    print(
        f"  {'localizer / controller':<{width}}  success  final error mean/p95  loc error mean/p95"
    )
    for e in result.summary():
        label = f"{e['localizer']} / {e['controller']}"
        fe, le = e["final_error_in"], e["loc_error_final_in"]
        print(
            f"  {label:<{width}}  {e['success_rate'] * 100:6.0f}%  "
            f"{fe['mean']:7.2f} / {fe['p95']:5.2f} in    {le['mean']:6.2f} / {le['p95']:5.2f} in"
        )
    out = Path(args.out or f"bench_{Path(args.scenario).stem}")
    try:
        from vexsim.bench.report import write_report

        path = write_report(result, out, worst_cases=not args.no_worst)
    except ModuleNotFoundError:
        from vexsim.bench.report import write_csv

        out.mkdir(parents=True, exist_ok=True)
        path = write_csv(out / "trials.csv", result.rows)
        print('note: install the viz extra for the HTML report: pip install -e ".[viz]"')
    print(f"wrote {path}")
    return EXIT_OK


def add_bench(sub) -> None:
    """The parser's commands: bench."""
    p = sub.add_parser(
        "bench",
        help="Monte-Carlo comparison of localizers and controllers on a scenario",
        description=(
            "Run every seed x localizer x controller of a scenario in parallel, then write "
            "trials.csv, summary.csv, worst-case telemetry and a self-contained report.html."
        ),
    )
    p.add_argument("scenario", help="scenario YAML file")
    p.add_argument("--seeds", type=int, default=20, help="number of seeds (default 20)")
    p.add_argument("--first-seed", type=int, default=0)
    p.add_argument("--workers", type=int, help="worker processes (default: CPU cores - 1)")
    p.add_argument("--localizers", help="comma-separated subset of the scenario's localizers")
    p.add_argument("--controllers", help="comma-separated subset of the scenario's controllers")
    p.add_argument("--out", help="output directory (default: bench_<scenario name>)")
    p.add_argument("--no-worst", action="store_true", help="skip re-running the worst cases")
    p.set_defaults(func=cmd_bench)
