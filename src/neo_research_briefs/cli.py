"""Command-line entry point.

Primary subcommands:

- ``run-once``            - one watcher cycle; lives under cron or an
                            OpenClaw scheduled session.
- ``validate-config``     - prints every config problem in one shot;
                            safe to run on any host before enabling a cron.
- ``obsidian``            - scans the vault and reports which files
                            parse, which do not, and which are eligible
                            to claim.
- ``emit-openclaw-cron``  - prints a ready-to-paste OpenClaw cron job
                            JSON object for this repo.
- ``scan-repo-safety``    - scans the repo for bespoke or potentially
                            sensitive setup details before push.

All commands respect ``--env-file`` / ``--json`` so that smoke tests
and humans see the same output shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .adapters.obsidian import ObsidianAdapter
from .config import Config, ConfigError, load_config
from .openclaw import build_cron_job
from .safety import scan_repo_for_bespoke_info
from .services.watcher import Watcher, WatcherReport


# ---------------------------------------------------------------------------
# Parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neo-briefs",
        description="OpenClaw research-brief orchestration.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to a .env file. Real environment variables still take precedence.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of human-readable text.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-once", help="Run one watcher cycle and exit.")
    run.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=None,
        help="Force dry-run mode for this invocation.",
    )
    run.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Force real execution (overrides NEO_BRIEFS_DRY_RUN=true).",
    )

    sub.add_parser(
        "validate-config",
        help="Validate configuration. Exits non-zero on problems.",
    )

    obs = sub.add_parser(
        "obsidian",
        help="Discover and validate research briefs in the configured Obsidian vault.",
    )
    obs.add_argument(
        "--show-want-only",
        action="store_true",
        help="Print only briefs whose status matches OBSIDIAN_WANT_VALUE.",
    )

    cron = sub.add_parser(
        "emit-openclaw-cron",
        help="Emit a ready-to-paste OpenClaw cron job JSON object.",
    )
    cron.add_argument(
        "--repo-dir",
        type=Path,
        default=Path.cwd(),
        help="Path to the checked-out repo on the watcher host.",
    )
    cron.add_argument(
        "--cron-env-file",
        type=Path,
        default=None,
        help="Optional .env path for the wrapper command embedded in the cron prompt.",
    )
    cron.add_argument(
        "--every-minutes",
        type=int,
        default=5,
        help="Run interval in minutes.",
    )
    cron.add_argument(
        "--session-target",
        default="isolated",
        help="OpenClaw cron sessionTarget value, usually isolated or current.",
    )
    cron.add_argument(
        "--delivery-mode",
        default="none",
        help="OpenClaw cron delivery.mode value.",
    )
    cron.add_argument(
        "--job-name",
        default="research-brief-intake",
        help="Human-readable cron job name.",
    )
    cron.add_argument(
        "--dry-run",
        dest="cron_dry_run",
        action="store_true",
        default=None,
        help="Force the embedded command to run the watcher in dry-run mode.",
    )
    cron.add_argument(
        "--no-dry-run",
        dest="cron_dry_run",
        action="store_false",
        help="Force the embedded command to run the watcher live.",
    )

    safety = sub.add_parser(
        "scan-repo-safety",
        help="Scan the repo for bespoke or potentially sensitive setup info.",
    )
    safety.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repo root to scan.",
    )

    return parser


# ---------------------------------------------------------------------------
# Command handlers


def _cmd_run_once(args: argparse.Namespace, config: Config, *, json_out: bool) -> int:
    if args.dry_run is not None:
        config.dry_run = args.dry_run

    problems = config.validate()
    if problems:
        _emit("configuration invalid:", json_out=json_out, payload={"errors": problems})
        if not json_out:
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        return 2

    watcher = Watcher(config)
    report = watcher.run_once()
    _render_report(report, json_out=json_out)
    return 0 if not report.errors else 1


def _cmd_validate_config(config: Config, *, json_out: bool) -> int:
    problems = config.validate()
    if json_out:
        print(
            json.dumps(
                {
                    "ok": not problems,
                    "enabled_adapters": sorted(config.enabled_adapters),
                    "dry_run": config.dry_run,
                    "problems": problems,
                },
                indent=2,
            )
        )
    else:
        print("Enabled adapters:", ", ".join(sorted(config.enabled_adapters)) or "(none)")
        print(f"Dry run: {config.dry_run}")
        print(f"Claimer: {config.claimer}")
        print(f"Max per run: {config.max_per_run}")
        if problems:
            print("\nProblems:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print("\nConfiguration looks OK.")
    return 0 if not problems else 2


def _cmd_obsidian(args: argparse.Namespace, config: Config, *, json_out: bool) -> int:
    if not config.obsidian.is_configured():
        _emit(
            "OBSIDIAN_VAULT_PATH is not configured.",
            json_out=json_out,
            payload={"error": "OBSIDIAN_VAULT_PATH not configured"},
        )
        return 2

    adapter = ObsidianAdapter(config.obsidian)
    briefs, problems = adapter.scan()

    want_value = config.obsidian.want_value.strip().lower()
    rows = []
    for brief_file in briefs:
        status = brief_file.get_str(config.obsidian.status_field, "").strip().lower()
        is_want = status == want_value
        if args.show_want_only and not is_want:
            continue
        rows.append(
            {
                "path": str(brief_file.path),
                "title": brief_file.get_str("title") or brief_file.path.stem,
                "status": status or "(unset)",
                "is_want": is_want,
                "tags": brief_file.get_list("tags"),
            }
        )

    if json_out:
        print(
            json.dumps(
                {
                    "briefs_dir": str(config.obsidian.briefs_dir()),
                    "ok": len(briefs),
                    "problems": [{"path": str(p), "error": m} for p, m in problems],
                    "briefs": rows,
                },
                indent=2,
            )
        )
    else:
        print(f"Scanning {config.obsidian.briefs_dir()}")
        print(f"Parsed OK: {len(briefs)} | Problems: {len(problems)}")
        if problems:
            print("\nParse problems:")
            for path, message in problems:
                print(f"  - {path}: {message}")
        if rows:
            print("\nBriefs:")
            for row in rows:
                marker = "*" if row["is_want"] else " "
                print(f"  {marker} [{row['status']}] {row['title']}  ({row['path']})")
        else:
            print("\nNo briefs to display.")
    return 0 if not problems else 1


def _cmd_emit_openclaw_cron(args: argparse.Namespace, *, json_out: bool) -> int:
    try:
        job = build_cron_job(
            args.repo_dir,
            env_file=args.cron_env_file,
            every_minutes=args.every_minutes,
            session_target=args.session_target,
            delivery_mode=args.delivery_mode,
            job_name=args.job_name,
            dry_run=args.cron_dry_run,
        )
    except ValueError as exc:
        _emit(str(exc), json_out=json_out, payload={"error": str(exc)})
        return 2

    print(json.dumps(job, indent=2))
    return 0


def _cmd_scan_repo_safety(args: argparse.Namespace, *, json_out: bool) -> int:
    findings = scan_repo_for_bespoke_info(args.root)
    payload = {
        "root": str(args.root.resolve()),
        "ok": not findings,
        "findings": [asdict(finding) for finding in findings],
    }
    if json_out:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Scanning {payload['root']}")
        if not findings:
            print("No bespoke or potentially sensitive setup details found.")
        else:
            print(f"Found {len(findings)} possible issue(s):")
            for finding in findings:
                print(
                    f"  - {finding.path}:{finding.line} [{finding.kind}] {finding.match}\n"
                    f"      {finding.snippet}"
                )
    return 0 if not findings else 1


# ---------------------------------------------------------------------------
# Rendering helpers


def _render_report(report: WatcherReport, *, json_out: bool) -> None:
    if json_out:
        payload = {
            "started_at": report.started_at.isoformat(),
            "dry_run": report.dry_run,
            "actions": [_action_to_dict(a) for a in report.actions],
            "summary": report.summary_line(),
        }
        print(json.dumps(payload, indent=2))
        return

    print(report.summary_line())
    for action in report.actions:
        line = f"  [{action.action}] {action.title}  ({action.source.value}:{action.brief_id})"
        if action.detail:
            line += f"\n      {action.detail}"
        if action.discord_thread_url:
            line += f"\n      discord: {action.discord_thread_url}"
        if action.github_issue_url:
            line += f"\n      issue: {action.github_issue_url}"
        print(line)


def _action_to_dict(action) -> dict:
    data = asdict(action)
    data["source"] = action.source.value
    data["occurred_at"] = action.occurred_at.isoformat()
    return data


def _emit(message: str, *, json_out: bool, payload: dict | None = None) -> None:
    if json_out:
        print(json.dumps(payload or {"message": message}, indent=2))
    else:
        print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    env_file = args.env_file
    if env_file is None:
        default = Path.cwd() / ".env"
        if default.exists():
            env_file = default

    json_out = bool(args.json)

    if args.command == "emit-openclaw-cron":
        return _cmd_emit_openclaw_cron(args, json_out=json_out)
    if args.command == "scan-repo-safety":
        return _cmd_scan_repo_safety(args, json_out=json_out)

    try:
        config = load_config(dotenv_path=env_file)
    except ConfigError as exc:
        _emit(
            f"configuration error: {exc}",
            json_out=json_out,
            payload={"error": str(exc)},
        )
        return 2

    if args.command == "run-once":
        return _cmd_run_once(args, config, json_out=json_out)
    if args.command == "validate-config":
        return _cmd_validate_config(config, json_out=json_out)
    if args.command == "obsidian":
        return _cmd_obsidian(args, config, json_out=json_out)

    parser.error(f"unknown command: {args.command}")
    return 2  # argparse.error exits, but keep the type checker happy.


if __name__ == "__main__":  # pragma: no cover - CLI glue
    raise SystemExit(main())
