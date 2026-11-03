# Forgetting a cached page

Delete a stale local title through the backend API, without modifying a wiki or
opening the database directly:

```bash
uv run wtbot --base-url http://127.0.100.1:18564 page delete \
  --label Wikisource \
  'Book:The Principles of Psychology (James)/Chapter 9'
```

This previews the title, revision, page-link, revision-link and promotion-batch
records that would be removed. Add `--force` to perform the deletion. Root
tracking records attached to a deleted pairing are removed too. Other sites'
titles and revisions, shared content still in use, and subpages are kept.
Pending fetches for the deleted cached title are cancelled by the normal cache
deletion machinery.

Uncommitted local edits block deletion unless `--discard-local-edits` is also
supplied. Structural dependants, such as pages belonging to an Index, still
block deletion; use the existing recursive `wtbot vfs delete` workflow for
removing an entire Index and its dependent pages.

The new command requires a backend running the matching code. Restart an older
backend before using it, then retry the original fetch after deleting the stale
entry.
