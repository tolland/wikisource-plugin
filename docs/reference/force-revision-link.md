# Resume a local-to-remote sync after divergence

Use `wtbot link revision` to accept correspondence between two explicit wiki
revision IDs even when their content differs. The command previews by default;
`--force` records the link. Recording a link does not edit either wiki.

1. Refresh the cached histories for both pages.
2. Find their pairing with `wtbot link pairs`.
3. Inspect the revisions in the wikis, or use `wtbot link revisions PAIR_PK`.
   IDs are the wiki's `oldid`/revision IDs, not wtbot database primary keys.
4. Choose the remote's current revision and the local revision immediately before
   the changes you want to push. This is often the parent of local HEAD. Linking
   both HEADs would leave no changes to push.
5. Preview the exact selection (example pairing 4, local revision 11, remote 902):

   ```bash
   uv run wtbot link revision 4 --local-revid 11 --remote-revid 902
   ```

6. Check the displayed site labels, page titles, and revision IDs, then record it:

   ```bash
   uv run wtbot link revision 4 --local-revid 11 --remote-revid 902 --force
   ```

7. Run `wtbot sync report --from Index:Book.djvu --source LOCAL --target REMOTE`,
   then review, stage, and push the outstanding changes using the sync workflow.
   This accepts replacement of remote content by the subsequent local revisions.

Both selected revisions must already be cached for the pairing. The preview is
read-only and uses the cache; it does not fetch from the wikis or guarantee the
remote is still at its cached HEAD. The write uses the existing revision-link
validation. If a chosen revision already has a different counterpart on that
site, retract that rung using `wtbot link unpair-revision LINK_PK` before retrying.
Other sync checks still apply.

The global `--base-url` option can select a different wtbot service, for example:

```bash
uv run wtbot --base-url http://127.0.100.1:18564 link revision 4 \
  --local-revid 11 --remote-revid 902
```
