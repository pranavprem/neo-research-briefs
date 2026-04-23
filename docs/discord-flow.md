# Discord flow

Discord is the human collaboration surface. The watcher only touches it
twice per brief: it creates an implementation thread and posts a
starter message. Everything else happens inside the worker session.

## Intake channel

Create one dedicated channel, for example `#implement-research`. Every
implementation thread is a child of this channel, which gives humans a
single place to watch for new work.

Recommended channel settings:

- Topic: "Mark a Research Brief as Want in Notion and OpenClaw will
  start an implementation thread here."
- Slow mode off (threads carry the conversation).
- Pinned message linking to the Notion database and to this repo's
  runbook.

## Bot permissions

At minimum:

- View Channel
- Send Messages
- Read Message History
- Create Public Threads
- Send Messages in Threads
- Embed Links

Optional but useful:

- Manage Threads (for archiving or renaming after completion)
- Mention Everyone (only if paging behavior is intentional)

## Thread creation

One thread per brief. The thread name is derived from
`ResearchBrief.title` and truncated to Discord's 100-character limit.

The thread must be **public** by default so other team members can see
the work in progress. Use a private thread only if the brief is
sensitive (and in that case, also limit who has access to the Notion
page).

## Starter message

The starter message is the first message in the thread and sets
expectations for the humans reading it. It is assembled by
`DiscordAdapter.build_starter_message` and includes:

1. "Research brief claimed."
2. The brief title.
3. Summary (if present).
4. Why this matters (if present).
5. Source URL (if present).
6. A link back to the Notion page.
7. A short "Planned next steps" list.

Keep it terse. Humans will click through to Notion for detail.

## Idempotency

The watcher will not create a second thread for a brief that already
carries a `Discord Thread URL`. If a thread goes missing (deleted by a
human, for example), clear that URL in Notion before the next cycle.

## Rate limiting

If the watcher's cron interval is too aggressive, thread creation will
start returning 429s with a `Retry-After`. The watcher logs the error
against the brief and stops. Extend the cron interval before retrying.

## Post-completion hygiene

When a brief moves to `Done`, the worker session should:

- post a final summary with the PR or commit link,
- archive the thread (not lock it; archived threads reopen when a
  human replies, which is often what you want).

Deleting threads is rarely the right move - the history is often the
most useful artifact of the whole run.
