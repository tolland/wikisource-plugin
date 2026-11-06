# docs/

Start at [index.md](index.md). The folders are organised by audience:

| Folder | Holds |
|---|---|
| `user/` | How to use the shipped features. Present tense, written for someone who wasn't here. |
| `developer/` | How the plugin code works today, with a short "Why it is like this" where the rationale explains current code. |
| `internal/todo/` | Unbuilt work only. Delete an item when it ships; fold anything worth keeping into a `developer/` page. |
| `internal/design/` | Designs that are relevant but not scheduled. |
| `images/` | Screenshots used by the pages above. |

History lives in git, not in these pages. Every class, path and command a page
cites should exist in the current code.

wtbot (the HTTP backend) and its viewer are documented in their own repository,
`../wtbot`; link to them in plain text rather than duplicating their content.
