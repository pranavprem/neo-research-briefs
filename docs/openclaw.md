# OpenClaw integration

This is the last-mile path for another OpenClaw operator.

If the repo is already cloned on the watcher host, you should be able
to go from "fresh checkout" to "scheduled intake watcher" in a few
minutes.

## Quick start

```bash
git clone https://github.com/<you>/neo-research-briefs
cd neo-research-briefs
bash scripts/bootstrap.sh
```

That script:

- creates `.venv/` if needed,
- installs the package,
- creates `.env` from `.env.example` if missing,
- runs config validation,
- prints the next commands you should run.

## Wrapper command

The recommended wrapper for OpenClaw or system cron is:

```bash
bash scripts/run_neo_briefs.sh --json run-once
```

Why use the wrapper instead of a raw `python -m ...` command?

- it works whether or not a virtualenv exists,
- it pins execution to the repo root,
- it sets `PYTHONPATH=src`,
- it is short enough to embed in cron prompts and runbooks.

You can use the same wrapper for other commands too:

```bash
bash scripts/run_neo_briefs.sh --json validate-config
bash scripts/run_neo_briefs.sh --json obsidian
bash scripts/run_neo_briefs.sh --json scan-repo-safety
```

## Emit a ready-to-paste OpenClaw cron job

From the repo root:

```bash
bash scripts/run_neo_briefs.sh --json emit-openclaw-cron --repo-dir "$PWD"
```

Example output shape:

```json
{
  "name": "research-brief-intake",
  "schedule": { "kind": "every", "everyMs": 300000 },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Use exec to run the watcher wrapper and return only the command's JSON output.\nRepository: /path/to/neo-research-briefs\nCommand: cd /path/to/neo-research-briefs && bash scripts/run_neo_briefs.sh --json run-once\nIf the command exits non-zero, return the JSON or stderr summary once and do not retry in a loop."
  },
  "delivery": { "mode": "none" }
}
```

You can customize it:

```bash
bash scripts/run_neo_briefs.sh --json emit-openclaw-cron \
  --repo-dir "$PWD" \
  --every-minutes 10 \
  --session-target isolated \
  --delivery-mode none
```

If you keep your environment file somewhere else:

```bash
bash scripts/run_neo_briefs.sh --json emit-openclaw-cron \
  --repo-dir "$PWD" \
  --cron-env-file /secure/path/neo-research-briefs.env
```

## Recommended OpenClaw job settings

- `sessionTarget: "isolated"` for intake polling
- `delivery.mode: "none"` unless you explicitly want cron completion chat noise
- 5 minutes is a sane default
- keep `NEO_BRIEFS_DRY_RUN=true` until you have validated the intake flow

## Pre-push safety pass

Before pushing docs or config changes from a real deployment, run:

```bash
bash scripts/run_neo_briefs.sh --json scan-repo-safety
```

This catches common bespoke details that should not leak into a public repo:

- RFC1918 private IPs like `10.x.x.x`
- absolute home paths like `/path/to/your/home/...`
- custom local/internal domains
- Discord-style IDs when they appear in channel/guild/user context

It is intentionally conservative. Treat findings as review prompts, not gospel.

## What not to commit

Do not commit:

- populated `.env` files,
- internal IPs or NAS hostnames,
- personal home-directory paths,
- real Discord channel or guild identifiers,
- custom internal service URLs,
- copied logs containing tokens or approval links.

Keep the repo portable. Another OpenClaw should be able to copy the
docs and scripts without inheriting your personal infrastructure.
