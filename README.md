# neo-research-briefs

Turn research briefs into an implementation pipeline across Notion,
Discord, GitHub, and (optionally) Obsidian.

This README is written for another OpenClaw operator who wants to
reproduce the workflow from scratch. The Python package under `src/`
is the v1 reference implementation; the README also describes the
contract so an operator using a different language or harness can
reproduce the behavior without reading the code.

## What this system does

A human finds an interesting idea, tool, integration, or workflow and
saves it as a **Research Brief**. The brief can live in:

- a dedicated Notion database, or
- a folder of Markdown files in an Obsidian vault,

or both at once.

When a brief's status changes to **Want**, OpenClaw should:

1. detect the brief,
2. claim it without creating duplicates,
3. create a Discord implementation thread,
4. start the actual work,
5. write thread and GitHub links back to the source,
6. move the brief through implementation and review states.

The important idea is simple:

- **Notion or Obsidian** is the intake and planning surface.
- **Discord** is the human collaboration surface.
- **GitHub** is the durable build surface.
- **OpenClaw** is the orchestrator.

## Recommended operating model

Pick one intake source, at least to start:

- **Notion** if your team already plans there and a shared database
  with write-back is the natural home for briefs.
- **Obsidian** if you already keep notes in a vault and would rather
  not juggle an API token. No network calls, no secrets.

You can enable both later. Both normalize into the same `ResearchBrief`
type internally, so the watcher does not care where a brief came from.

Treat the workflow like this:

- New idea captured in Notion or Obsidian
- Human reviews and marks it **Want**
- OpenClaw claims it and opens a Discord thread
- OpenClaw executes in that thread or through a linked worker session
- Results become GitHub issues, branches, PRs, docs, or a finished
  repo change
- Brief moves to **Review** and then **Done**

## Prerequisites

You need:

- a running OpenClaw instance,
- Python 3.10+ on the watcher host,
- Discord connected through the `message` tool,
- at least one of: a Notion integration, or an Obsidian vault on disk,
- GitHub access through `gh auth login` (optional),
- a dedicated Discord channel, for example `#implement-research`.

Optional but strongly recommended:

- a dedicated long-lived OpenClaw session for this workflow,
- a separate repo per implementation target,
- a test or dry-run mode before you let it write to Notion, Discord,
  or the vault.

## 0. Install

Manual path:

```bash
git clone https://github.com/<you>/neo-research-briefs
cd neo-research-briefs
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Or use the repo bootstrap:

```bash
git clone https://github.com/<you>/neo-research-briefs
cd neo-research-briefs
bash scripts/bootstrap.sh
```

Then edit `.env` to enable the adapters you use. `NEO_BRIEFS_DRY_RUN`
stays `true` by default, do not flip it until the dry-run output
looks right.

The wrapper command used throughout the rest of this README is:

```bash
bash scripts/run_neo_briefs.sh --json validate-config
```

That wrapper works even if the repo has only been cloned and not yet
installed into the active shell.

## 1. Pick an intake source

### Option A: Obsidian vault

The fastest way to get started. No API keys, no database, no tokens.

1. Pick a folder in your vault, for example `Research Briefs/`.
2. Set `OBSIDIAN_VAULT_PATH=/absolute/path/to/YourVault` in `.env`.
3. (Optional) Set `OBSIDIAN_BRIEFS_FOLDER=Research Briefs`.
4. Copy `templates/obsidian/research-brief.md` into the folder and
   fill it in.

See [`docs/obsidian.md`](docs/obsidian.md) for the frontmatter
reference and [`docs/architecture.md`](docs/architecture.md) for the
end-to-end flow.

### Option B: Notion database

Create a new database called **Research Briefs**.

Minimum useful properties:

| Property | Type | Purpose |
|---|---|---|
| Name | Title | Brief title |
| Status | Select | Workflow state |
| Summary | Rich text | One-paragraph explanation |
| Why it matters | Rich text | Why you care |
| Category | Select | Tool, Workflow, Integration, Repo, Automation, etc. |
| Effort | Select | Small, Medium, Large |
| Source URL | URL | Original link or reference |
| Notes | Rich text | Extra context |
| Discord Thread URL | URL | Thread opened by OpenClaw |
| GitHub Issue URL | URL | Optional issue created from the brief |
| GitHub PR URL | URL | Optional PR created from the work |
| Claimed By | Rich text | Agent/session name |
| Claimed At | Date | When the watcher took it |
| Last Sync At | Date | Last successful automation write-back |
| Error | Rich text | Last failure message if something broke |
| Target Repo | Rich text | Repo the work should land in |

Recommended `Status` options:

- Backlog
- Want
- Implementing
- Review
- Done
- Dropped

The only truly special value is **Want**. That is the intake trigger.

The full schema and write-back rules live in
[`docs/notion-schema.md`](docs/notion-schema.md).

### Important rule (either source)

Store the actual brief content either in the page body or in rich text
fields (Notion) or the file body (Obsidian). OpenClaw needs enough
context to open a thread without guessing.

A good brief usually includes:

- what the thing is,
- why it is interesting,
- what problem it solves,
- what "done" would look like,
- where it should be implemented.

## 2. Create the Discord channel

Create a dedicated channel such as `#implement-research`.

The bot/account used by OpenClaw should have at least:

- View Channel
- Send Messages
- Read Message History
- Create Public Threads
- Send Messages in Threads
- Embed Links

Useful extras:

- Manage Threads
- Mention Everyone, if you intentionally want paging behavior

Set the channel topic to something like:

> Mark a Research Brief as Want and OpenClaw will start an
> implementation thread here.

The full Discord contract (thread naming, starter message, rate
limits, post-completion hygiene) lives in
[`docs/discord-flow.md`](docs/discord-flow.md).

## 3. Prepare GitHub access

Authenticate GitHub CLI on the OpenClaw host:

```bash
gh auth login
gh auth status
```

At minimum, make sure the token can:

- read repos,
- create issues,
- create pull requests,
- read workflow runs if you want CI feedback.

If the brief is only for discussion and not code, GitHub can stay
optional. If the brief should result in implementation work, GitHub
should be part of the loop.

## 4. Decide how work should execute

You have three good patterns.

### Pattern A: simple watcher

- Cron wakes an isolated OpenClaw run every 5 minutes.
- The run executes `neo-briefs run-once`.
- The watcher claims any `Want` brief.
- It creates the Discord thread.
- It posts a starter message.
- It exits.

Use this if you only want intake automation.

### Pattern B: watcher plus background worker

- Cron watcher claims the brief and creates the thread.
- The watcher then spawns a worker session to do the actual
  implementation.
- The worker posts progress back into the thread.

Use this if implementation might take more than one turn.

### Pattern C: thread-bound ACP coding session

If a brief should kick off real coding work with Codex or another ACP
harness:

- create the thread as part of the session flow,
- spawn a persistent thread-bound ACP session,
- let that session own the implementation conversation.

Use this when each brief becomes a real coding track rather than a
lightweight task.

## 5. The watcher contract

Language does not matter much here. Python, TypeScript, or pure
OpenClaw orchestration are all fine. The contract matters.

Your watcher should do this every run:

1. query enabled sources for briefs where `Status = Want`,
2. skip briefs that already have a thread or active claim,
3. claim one brief at a time or claim a small batch safely,
4. update the source immediately to mark it `Implementing`,
5. create a Discord thread in the intake channel,
6. send a starter message with summary, source link, and next steps,
7. write the Discord thread URL back to the source,
8. optionally create a GitHub issue and write that back too,
9. optionally spawn the actual worker session,
10. store any failure in the `Error` field (Notion) or
    `error:` frontmatter key (Obsidian).

### Pseudocode

```text
briefs = source.query(status="Want")

for brief in briefs:
  if brief.discord_thread_url exists:
    continue

  if brief.claimed_by exists and brief.status != "Want":
    continue

  claim brief:
    status = "Implementing"
    claimed_by = "openclaw:research-briefs"
    claimed_at = now
    error = ""

  create discord thread under #implement-research
  post starter message

  write back:
    discord_thread_url = thread.url
    last_sync_at = now

  if brief.target_repo exists:
    optionally create github issue
    write github_issue_url back to the source

  optionally spawn worker session
```

The reference Python implementation lives in
`src/neo_research_briefs/services/watcher.py`.

## 6. Be strict about idempotency

This part matters more than people think.

You do **not** want:

- duplicate Discord threads,
- two sessions working the same brief,
- a brief stuck in `Want` after partial success,
- a GitHub issue created twice.

Recommended protections:

- treat the Notion page ID (or the vault-relative path) as the
  canonical brief ID,
- write `Claimed By` and `Claimed At` before thread creation,
- if a thread already exists, reuse it,
- if a GitHub issue already exists, do not create another,
- if thread creation fails, write the error back clearly,
- only move back to `Want` manually or with an explicit retry rule.

Every write the Obsidian adapter performs uses `tempfile + os.replace`
so a crash never leaves half a frontmatter block on disk. See
[`docs/architecture.md`](docs/architecture.md) for the full
idempotency fence.

## 7. Register a cron watcher in OpenClaw

Use OpenClaw cron for exact timing. Five minutes is a good default.

The easiest path is to let the repo emit the job for you:

```bash
bash scripts/run_neo_briefs.sh --json emit-openclaw-cron --repo-dir "$PWD"
```

That prints a ready-to-paste job object that tells another OpenClaw to
run the wrapper command in this repo:

```bash
bash scripts/run_neo_briefs.sh --json run-once
```

You can customize the emitted job too:

```bash
bash scripts/run_neo_briefs.sh --json emit-openclaw-cron \
  --repo-dir "$PWD" \
  --every-minutes 10 \
  --session-target isolated \
  --delivery-mode none
```

More detail, including bootstrap and safety-scan guidance, lives in
[`docs/openclaw.md`](docs/openclaw.md).

## 8. CLI cheat sheet

The reference implementation ships a `neo-briefs` command plus a small
wrapper script at `scripts/run_neo_briefs.sh`.

```bash
# Validate configuration; exits non-zero on problems.
bash scripts/run_neo_briefs.sh --json validate-config

# Scan the Obsidian vault and list what parses, what does not, and
# which briefs are currently marked Want.
bash scripts/run_neo_briefs.sh --json obsidian --show-want-only

# Run one watcher cycle. Safe by default: NEO_BRIEFS_DRY_RUN=true.
bash scripts/run_neo_briefs.sh --json run-once --dry-run

# Real execution. Only flip this once the dry run looks right.
bash scripts/run_neo_briefs.sh --json run-once --no-dry-run

# Emit a ready-to-paste OpenClaw cron job.
bash scripts/run_neo_briefs.sh --json emit-openclaw-cron --repo-dir "$PWD"

# Scan the repo for bespoke or potentially sensitive setup details.
bash scripts/run_neo_briefs.sh --json scan-repo-safety
```

All commands accept `--json` for machine-readable output.

## 9. Starter thread message template

When OpenClaw creates the thread, the first message should be enough
for a human to understand the work immediately.

Suggested template:

```text
Research brief claimed.

Summary:
<1-3 sentence summary>

Why this matters:
<short rationale>

Source:
<link>

Planned next steps:
- confirm target repo or destination
- break work into implementation tasks
- start execution

Brief link:
<link to page or vault file>
```

If you are going to spawn a worker session, say that explicitly in the
thread. `DiscordAdapter.build_starter_message` produces this template.

## 10. Write-back rules

After thread creation, update the source with at least:

- `Status = Implementing`
- `Discord Thread URL`
- `Claimed By`
- `Claimed At`
- `Last Sync At`
- `Error = empty`

After work starts, optionally add:

- GitHub issue link
- GitHub PR link
- implementation notes
- review checklist

When work is ready for human verification:

- set `Status = Review`
- summarize what changed
- link the PR or commit

When work is complete:

- set `Status = Done`
- keep all artifact links on the page / file

## 11. Failure handling

You need boring, reliable failure behavior.

If the source query fails:

- do nothing destructive,
- log the failure,
- try again next run.

If claim succeeds but Discord thread creation fails:

- keep the brief in `Implementing`,
- write the failure into `Error`,
- retry only if you can prove no thread exists.

If the Discord thread is created but the source write-back fails:

- log the thread ID somewhere durable,
- retry the source write-back,
- do not create a second thread.

If GitHub issue creation fails:

- continue the thread work,
- mark the page with the error,
- retry GitHub separately.

More detail and triage runbooks in [`docs/runbook.md`](docs/runbook.md).

## 12. Repository layout

```text
.
├── README.md
├── pyproject.toml
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── notion-schema.md
│   ├── discord-flow.md
│   ├── obsidian.md
│   ├── openclaw.md
│   └── runbook.md
├── src/
│   └── neo_research_briefs/
│       ├── __init__.py
│       ├── config.py
│       ├── models.py
│       ├── cli.py
│       ├── openclaw.py
│       ├── safety.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── notion.py
│       │   ├── discord.py
│       │   ├── github.py
│       │   └── obsidian.py
│       └── services/
│           ├── __init__.py
│           └── watcher.py
├── scripts/
│   ├── bootstrap.sh
│   └── run_neo_briefs.sh
├── templates/
│   └── obsidian/
│       └── research-brief.md
└── tests/
    ├── test_config.py
    ├── test_discord.py
    ├── test_github.py
    ├── test_models.py
    ├── test_notion.py
    ├── test_obsidian.py
    ├── test_openclaw.py
    └── test_safety.py
```

All four adapters are usable in v1. Notion, Discord, and GitHub talk
to their live APIs, while Obsidian works directly on vault files. The
interfaces are still small and mockable so the watcher's control flow
stays easy to test.

## 13. Smoke test before going live

Before you trust the automation, run this checklist:

1. create a fake brief in Notion or in the vault,
2. set `Status = Want`,
3. run `neo-briefs run-once --dry-run` and confirm the brief appears
   in the planned actions,
4. flip `--no-dry-run` and wait for the watcher,
5. confirm exactly one Discord thread appears,
6. confirm the thread starter message is correct,
7. confirm the source receives the thread URL,
8. confirm rerunning the watcher does **not** create a duplicate
   thread,
9. confirm failures get written back cleanly (break GitHub temporarily
   to exercise the error path).

Do this before you let the system touch real implementation work.

## 14. Practical advice

A few design choices will save you pain:

- keep the trigger narrow, only `Want` should auto-start work,
- keep the write-back fields explicit,
- prefer a dedicated intake channel over mixing this into general
  chat,
- reuse Discord threads instead of trying to be clever,
- make the agent announce real progress, not constant noise,
- keep the human in charge of prioritization,
- let GitHub hold the code truth, not Notion / Obsidian.

## 15. End state you are aiming for

When this is working well, the experience should feel like this:

- the human curates interesting ideas in their intake surface,
- one status change turns an idea into active work,
- Discord gets a clean implementation thread,
- OpenClaw picks up the work without duplicate chaos,
- GitHub captures the actual engineering artifacts,
- the intake surface remains the readable dashboard.

That is the whole point of `neo-research-briefs`.

It is not just a database.
It is a bridge from curiosity to execution.
