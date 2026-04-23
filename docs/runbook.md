# Runbook

Operational notes for running `neo-research-briefs` in production (or
pretending to).

## Daily / weekly

- Once a week, `neo-briefs obsidian` (or `validate-config`) should run
  green. If it does not, something regressed in your vault or your env.
- Watch the Discord intake channel. New threads without a Notion
  back-link indicate a write-back failure; check the brief's `Error`
  field or frontmatter `error` value.
- Skim briefs stuck in `Implementing` for more than a week. Either a
  worker session is still in flight (fine) or the handoff broke (not
  fine).

## Starting from scratch on a new host

1. `git clone` and `pip install -e '.[dev]'`.
2. `cp .env.example .env` and fill in the adapters you use.
3. `neo-briefs validate-config` - should report no problems.
4. `neo-briefs obsidian` (if the vault adapter is enabled) - should
   list briefs without parse errors.
5. `neo-briefs run-once --dry-run` - should report the briefs that
   *would* be claimed.
6. Flip `NEO_BRIEFS_DRY_RUN=false` (or pass `--no-dry-run`) only when
   the dry run matches your expectations.

## Scheduled execution

Two supported patterns; pick one.

### OpenClaw cron

```json
{
  "name": "research-brief-intake",
  "schedule": { "kind": "every", "everyMs": 300000 },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run `neo-briefs run-once`. Report the JSON summary."
  },
  "delivery": { "mode": "none" }
}
```

### System cron

```cron
*/5 * * * * cd /srv/neo-research-briefs && . .venv/bin/activate && neo-briefs run-once --json >> logs/watcher.log 2>&1
```

Five minutes is a sane default. Going faster will hit Discord rate
limits; going slower makes the end-to-end latency feel sluggish.

## Incident response

### A duplicate thread appeared

- Look at the Notion page (or vault frontmatter). If `Discord Thread
  URL` is empty, the earlier run never wrote back. Archive the
  duplicate by hand, then paste the canonical URL back into Notion.
- Check the previous watcher log for write-back errors. Fix the
  underlying problem before running again.

### A brief is stuck in `Want`

- Pull it up in the source. If `Claimed By` is set and `Status` is
  still `Want`, the claim succeeded but the status write failed; flip
  the status manually to `Implementing`.
- Confirm the adapter is enabled in `NEO_BRIEFS_ENABLED_ADAPTERS`.
- Confirm the watcher is actually running (`crontab -l` or the
  OpenClaw cron dashboard).

### The watcher is spamming errors

1. Stop the cron.
2. Run `neo-briefs run-once --dry-run --json` and inspect the output.
3. Fix the underlying config or code problem.
4. Resume the cron.

Never "just retry" while an adapter is raising unexpected errors -
that is how duplicates get created.

## Rollback

The watcher only writes to:

- Notion properties in the Research Briefs database,
- Obsidian brief frontmatter,
- one Discord thread per brief,
- optionally one GitHub issue per brief.

There is no stateful queue and no database. To "roll back" a bad run:

1. Clear the automation-owned Notion properties (or frontmatter) for
   the affected briefs.
2. Archive the Discord threads (do not delete - the history is the
   cheapest source of truth).
3. Close the GitHub issues.
4. Flip the briefs back to `Want` or `Backlog`.

## Observability

- `--json` output on every CLI command is intentionally stable. Feed
  it into `jq`, a log aggregator, or a status dashboard.
- `WatcherReport.summary_line()` is designed to be grep-friendly.
- Nothing logs brief *content* at the INFO level - only IDs and
  titles. Do not lower that bar; briefs often contain customer or
  partner context.
