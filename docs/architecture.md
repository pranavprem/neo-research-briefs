# Architecture

`neo-research-briefs` is a small orchestration layer. It does one thing:
turn a research brief into an implementation pipeline. The rest of this
document explains how the pieces fit together so that a new operator
can skim it once and understand the code.

## Layers

```
            +--------------------+
            |  cli.py (argparse) |
            +---------+----------+
                      |
                      v
            +--------------------+
            |  services/watcher  |
            +----+---------+-----+
                 |         |
     +-----------+         +-------------+
     v                                   v
+--------------+                  +---------------+
| domain model |<-----------------|   adapters/   |
|  (models.py) |                  | notion/ disc/ |
+--------------+                  | gh/ obsidian  |
                                  +---------------+
```

- `models.py` owns the `ResearchBrief` dataclass and the `BriefStatus`
  enum. No I/O. No adapter imports.
- `adapters/` each expose a small, mockable class. Only the Obsidian
  adapter is fully implemented in v1; the others are documented stubs
  that raise `NotImplementedError` from their network methods.
- `services/watcher.py` holds the control flow. It collects briefs from
  whichever adapters are enabled, decides what to do with each one,
  and emits a `WatcherReport`.
- `cli.py` is the only place argparse, stdout, and `sys.exit` live.

Keeping those layers separate is what makes the watcher testable
without network mocks: tests build a `Config` pointing at a temp
vault, drop in fake adapters, and assert on the report.

## Sources of briefs

Briefs enter the system from two places:

1. **Notion** - a dedicated "Research Briefs" database. Trigger is the
   `Status` property flipping to `Want`.
2. **Obsidian** - a folder of `.md` files inside a vault. Trigger is
   the `status` frontmatter field flipping to `want`.

Both sources normalize into the same `ResearchBrief` dataclass, so the
watcher's per-brief logic is source-agnostic.

## The one-cycle contract

A single `Watcher.run_once()` call must:

1. **Collect.** Query every enabled source for `Want` briefs.
2. **Validate.** Reject briefs that are missing required fields. Bad
   data is recorded, not silently corrected.
3. **Gate.** Skip briefs that already have a Discord thread, a claim
   stamp, or any other sign that a prior run did the work. This is the
   idempotency fence.
4. **Act (or dry-run).** In dry-run mode, emit a `dry-run` action and
   stop. Otherwise, create the Discord thread, optionally create a
   GitHub issue, and write artifacts back to the source.
5. **Record.** Produce a `WatcherReport` describing every action. The
   CLI renders it; cron captures the stdout.

At most `NEO_BRIEFS_MAX_PER_RUN` briefs are processed per cycle. A
misconfigured cron can at worst create that many duplicate threads,
never a stampede.

## Idempotency rules

- The Notion page ID (or the Obsidian vault-relative path) is the
  canonical brief identifier; the watcher never mints its own.
- A brief is claimable only if its status is `Want` **and** no
  downstream artifact is set **and** no claim stamp is present.
- Write-backs are ordered: claim stamp first, then Discord thread,
  then GitHub issue, then clear the error field. If any step fails,
  later steps do not run and the next cycle sees a partially-claimed
  brief that the gate can handle.
- Obsidian writes use `tempfile + os.replace` so a crash never leaves
  half a frontmatter block on disk.

## Failure model

- Exceptions raised by an adapter are caught by the watcher and
  recorded as an `error` action on that one brief. The watcher does
  not re-raise; one bad brief must not poison the whole cycle.
- `NotImplementedError` is treated as a friendly error, not a crash.
  That is how the Notion/Discord/GitHub stubs behave today.
- The watcher never retries. The next scheduled run is the retry.

## Extension points

- **New source.** Add an adapter with `list_want_briefs()` returning
  `ResearchBrief` instances and a write-back method. Register it in
  `Watcher._collect_briefs` and `_write_back`.
- **New artifact.** Extend `WatcherAction` and add adapter calls in
  `Watcher._process_brief`.
- **New CLI subcommand.** `cli._build_parser` is the single place
  that declares commands. Keep each command handler small and pure.
