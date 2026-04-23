# Obsidian vault path

Obsidian is a first-class source for research briefs. If you already
keep notes in an Obsidian vault, pointing the watcher at a folder of
`.md` files is a zero-network way to drive the pipeline. No API keys,
no database, no integration tokens.

## Layout

Pick (or create) a folder in your vault. The default is
`Research Briefs/`. Every `.md` file directly inside that folder (and
its subfolders) is treated as a brief.

```
YourVault/
└── Research Briefs/
    ├── prompt-caching-playbook.md
    ├── shared-secrets-audit.md
    └── tools/
        └── ripgrep-cheatsheet.md
```

The adapter walks the folder recursively so you can organize briefs by
category without changing configuration.

## Frontmatter

Every brief file needs a YAML frontmatter block. The adapter only
understands the narrow YAML subset described in
[`architecture.md`](./architecture.md): scalars, booleans, nulls,
inline lists, and block lists. No nested maps. No multiline strings.

```yaml
---
title: Evaluate pgvector vs pgvector-scale for embeddings
status: want
summary: Investigate pgvector-scale's claims against pgvector for 10M+ vectors.
why_it_matters: We are about to commit to an index type; switching later is costly.
source_url: https://example.com/pgvector-scale-announcement
target_repo: pranavprem/embeddings-bench
tags:
  - database
  - embeddings
---
```

Field reference:

| Field | Required | Notes |
|---|---|---|
| `title` | no | Falls back to the file stem. |
| `status` | yes | One of `backlog`, `want`, `implementing`, `review`, `done`, `dropped`. |
| `summary` | no | Quoted into the Discord starter message. |
| `why_it_matters` | no | Also quoted into the starter message. |
| `source_url` | no | Must start with `http://` or `https://` if present. |
| `target_repo` | no | `owner/name` form, validated on load. |
| `tags` | no | List. Rendered in `neo-briefs obsidian` output. |
| `discord_thread_url` | no | Written by the watcher. |
| `github_issue_url` | no | Written by the watcher. |
| `claimed_by` | no | Written by the watcher. |
| `claimed_at` | no | Written by the watcher (ISO 8601). |
| `last_sync_at` | no | Written by the watcher (ISO 8601). |
| `error` | no | Written by the watcher on failure. |

## CLI workflow

```bash
# See what the adapter found and whether any files fail to parse.
neo-briefs obsidian

# Show only briefs currently marked "want".
neo-briefs obsidian --show-want-only

# Dry-run a full watcher cycle against the vault.
neo-briefs run-once --dry-run
```

## Write-back behavior

When the watcher claims a vault brief, it updates the frontmatter in
place using an atomic `tempfile + os.replace`. The body of the file is
preserved byte-for-byte. Lists are rewritten as block lists so diffs
stay line-aligned; this is the only cosmetic change the watcher makes.

If the file was under a cloud sync client (Obsidian Sync, iCloud,
Dropbox) the rewrite is still atomic locally. Sync clients occasionally
create `.conflict` copies if two devices edit the same file inside the
same second; prefer to let the watcher own the frontmatter and write
body content from devices.

## Common problems

- **"frontmatter opened with `---` but has no closing `---`"** - the
  file has `---` on its own line somewhere else that the parser treats
  as the terminator. Move content that starts with `---` out of the
  body, or indent it.
- **"unknown status"** - the frontmatter `status` value is not one of
  the six recognized states. The watcher refuses to claim a brief it
  cannot classify; correct the status or delete the field.
- **File parses but does not show up.** Check that it is inside the
  `OBSIDIAN_BRIEFS_FOLDER` and has a `.md` extension.
