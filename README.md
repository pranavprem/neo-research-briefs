# neo-research-briefs

Turn research briefs into an implementation pipeline across Notion, Discord, and GitHub.

This README is written for another OpenClaw operator who wants to reproduce the workflow from scratch.

## What this system does

A human finds an interesting idea, tool, integration, or workflow and saves it as a **Research Brief** in Notion.

When the brief's status changes to **Want**, OpenClaw should:

1. detect the brief,
2. claim it without creating duplicates,
3. create a Discord implementation thread,
4. start the actual work,
5. write thread and GitHub links back to Notion,
6. move the brief through implementation and review states.

The important idea is simple:

- **Notion** is the intake and planning surface.
- **Discord** is the human collaboration surface.
- **GitHub** is the durable build surface.
- **OpenClaw** is the orchestrator.

## Recommended operating model

Do **not** overload your general task database for this.
Create a dedicated **Research Briefs** database in Notion.

Treat the workflow like this:

- New idea captured in Notion
- Human reviews and marks it **Want**
- OpenClaw claims it and opens a Discord thread
- OpenClaw executes in that thread or through a linked worker session
- Results become GitHub issues, branches, PRs, docs, or a finished repo change
- Brief moves to **Review** and then **Done**

## Prerequisites

You need:

- a running OpenClaw instance,
- Discord connected through the `message` tool,
- a Notion integration or local helper script that can read and update your database,
- GitHub access through `gh auth login`,
- a dedicated Discord channel, for example `#implement-research`.

Optional but strongly recommended:

- a dedicated long-lived OpenClaw session for this workflow,
- a separate repo per implementation target,
- a test or dry-run mode before you let it write to Notion and Discord.

## 1. Create the Notion database

Create a new database called something like **Research Briefs**.

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

### Important rule

Store the actual brief content either in the page body or in rich text fields. OpenClaw needs enough context to open a thread without guessing.

A good brief usually includes:

- what the thing is,
- why it is interesting,
- what problem it solves,
- what “done” would look like,
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

> Mark a Research Brief as Want in Notion and OpenClaw will start an implementation thread here.

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

If the brief is only for discussion and not code, GitHub can stay optional.
If the brief should result in implementation work, GitHub should be part of the loop.

## 4. Decide how work should execute

You have three good patterns.

### Pattern A, simple watcher

- Cron wakes an isolated OpenClaw run every 5 minutes.
- The run checks Notion.
- It claims any `Want` brief.
- It creates the Discord thread.
- It posts a starter message.
- It exits.

Use this if you only want intake automation.

### Pattern B, watcher plus background worker

- Cron watcher claims the brief and creates the thread.
- The watcher then spawns a worker session to do the actual implementation.
- The worker posts progress back into the thread.

Use this if implementation might take more than one turn.

### Pattern C, thread-bound ACP coding session

If a brief should kick off real coding work with Codex or another ACP harness:

- create the thread as part of the session flow,
- spawn a persistent thread-bound ACP session,
- let that session own the implementation conversation.

Use this when each brief becomes a real coding track rather than a lightweight task.

## 5. Build the watcher contract

Language does not matter much here. Python, TypeScript, or pure OpenClaw orchestration are all fine.
The contract matters.

Your watcher should do this every run:

1. query Notion for briefs where `Status = Want`,
2. skip briefs that already have a thread or active claim,
3. claim one brief at a time or claim a small batch safely,
4. update Notion immediately to mark it `Implementing`,
5. create a Discord thread in the intake channel,
6. send a starter message with summary, source link, and next steps,
7. write the Discord thread URL back to Notion,
8. optionally create a GitHub issue and write that back too,
9. optionally spawn the actual worker session,
10. store any failure in the `Error` field.

### Pseudocode

```text
briefs = notion.query(status="Want")

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
    write github_issue_url back to notion

  optionally spawn worker session
```

## 6. Be strict about idempotency

This part matters more than people think.

You do **not** want:

- duplicate Discord threads,
- two sessions working the same brief,
- a brief stuck in `Want` after partial success,
- a GitHub issue created twice.

Recommended protections:

- treat the Notion page ID as the canonical brief ID,
- write `Claimed By` and `Claimed At` before thread creation,
- if a thread already exists, reuse it,
- if a GitHub issue already exists, do not create another,
- if thread creation fails, write the error back clearly,
- only move back to `Want` manually or with an explicit retry rule.

## 7. Register a cron watcher in OpenClaw

Use OpenClaw cron for exact timing.
Five minutes is a good default.

Example shape:

```json
{
  "name": "research-brief-intake",
  "schedule": {
    "kind": "every",
    "everyMs": 300000
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run the research brief intake watcher. Query Notion for briefs with Status=Want, claim them safely, create Discord threads in the configured intake channel, write links back to Notion, and spawn work sessions when appropriate. Be idempotent and avoid duplicate threads or duplicate GitHub artifacts."
  },
  "delivery": {
    "mode": "none"
  }
}
```

You can also use a named persistent session if you want continuity, but isolated runs are a good starting point.

## 8. Starter thread message template

When OpenClaw creates the thread, the first message should be enough for a human to understand the work immediately.

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

Notion brief:
<link to page>
```

If you are going to spawn a worker session, say that explicitly in the thread.

## 9. Write-back rules for Notion

After thread creation, update the page with at least:

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
- keep all artifact links on the page

## 10. Failure handling

You need boring, reliable failure behavior.

If Notion query fails:

- do nothing destructive,
- log the failure,
- try again next run.

If claim succeeds but Discord thread creation fails:

- keep the brief in `Implementing`,
- write the failure into `Error`,
- retry only if you can prove no thread exists.

If Discord thread is created but Notion write-back fails:

- log the thread ID somewhere durable,
- retry the Notion write-back,
- do not create a second thread.

If GitHub issue creation fails:

- continue the thread work,
- mark the page with the error,
- retry GitHub separately.

## 11. Suggested repository layout

As this repo grows, a clean layout would be:

```text
.
├── README.md
├── docs/
│   ├── architecture.md
│   ├── notion-schema.md
│   ├── discord-flow.md
│   └── runbook.md
├── src/
│   └── neo_research_briefs/
│       ├── watcher.py
│       ├── notion.py
│       ├── discord.py
│       ├── github.py
│       ├── models.py
│       └── worker.py
├── scripts/
│   ├── smoke_test.py
│   └── backfill_links.py
└── .env.example
```

## 12. Smoke test before going live

Before you trust the automation, run this checklist:

1. create a fake brief in Notion,
2. set `Status = Want`,
3. wait for the watcher,
4. confirm exactly one Discord thread appears,
5. confirm the thread starter message is correct,
6. confirm Notion receives the thread URL,
7. confirm rerunning the watcher does **not** create a duplicate thread,
8. confirm failures get written back cleanly.

Do this before you let the system touch real implementation work.

## 13. Practical advice

A few design choices will save you pain:

- keep the trigger narrow, only `Want` should auto-start work,
- keep the write-back fields explicit,
- prefer a dedicated intake channel over mixing this into general chat,
- reuse Discord threads instead of trying to be clever,
- make the agent announce real progress, not constant noise,
- keep the human in charge of prioritization,
- let GitHub hold the code truth, not Notion.

## 14. End state you are aiming for

When this is working well, the experience should feel like this:

- the human curates interesting ideas in Notion,
- one status change turns an idea into active work,
- Discord gets a clean implementation thread,
- OpenClaw picks up the work without duplicate chaos,
- GitHub captures the actual engineering artifacts,
- Notion remains the readable dashboard.

That is the whole point of `neo-research-briefs`.

It is not just a database.
It is a bridge from curiosity to execution.
