# Notion database schema

This document describes the exact shape of the `Research Briefs`
database that the Notion adapter expects. If you change a property
name, change the corresponding `NOTION_*` variable in `.env` too.

## Required properties

| Property | Type | Purpose |
|---|---|---|
| `Name` | Title | Brief title. |
| `Status` | Select | Workflow state. The only load-bearing value is `Want`. |

## Recommended properties

| Property | Type | Purpose |
|---|---|---|
| `Summary` | Rich text | One-paragraph explanation of the brief. |
| `Why it matters` | Rich text | Why you care - gets quoted into the Discord starter message. |
| `Category` | Select | Tool / Workflow / Integration / Repo / Automation / ... |
| `Effort` | Select | Small / Medium / Large. |
| `Source URL` | URL | Original link or reference. |
| `Notes` | Rich text | Extra context the author wants to preserve. |
| `Target Repo` | Rich text | `owner/name` of the repo where work should land. |

## Automation-owned properties

These are written by the watcher. Humans should not edit them directly
outside of a manual reset.

| Property | Type | Purpose |
|---|---|---|
| `Discord Thread URL` | URL | Thread opened by OpenClaw. |
| `GitHub Issue URL` | URL | Issue created from the brief (optional). |
| `GitHub PR URL` | URL | PR created by the worker session (optional). |
| `Claimed By` | Rich text | Agent/session identity, e.g. `openclaw:research-briefs`. |
| `Claimed At` | Date | UTC timestamp of the claim. |
| `Last Sync At` | Date | Last successful automation write-back. |
| `Error` | Rich text | Last failure message; cleared on a successful cycle. |

## Status options

Use exactly these names. They map onto `BriefStatus` in `models.py`.

- `Backlog`
- `Want`
- `Implementing`
- `Review`
- `Done`
- `Dropped`

## Trigger contract

The watcher queries for:

```json
{
  "filter": {
    "property": "Status",
    "select": { "equals": "Want" }
  }
}
```

If you change `Status` to a different property type (for example a
multi-select), update the Notion adapter query payload accordingly.

## Manual reset checklist

If you need to replay a brief through the pipeline:

1. Clear `Discord Thread URL`, `GitHub Issue URL`, `Claimed By`,
   `Claimed At`, `Last Sync At`, and `Error`.
2. Flip `Status` back to `Want`.
3. Wait for the next watcher cycle.

Do not clear these fields while the worker session is still active -
you will end up with two workers on one brief.
