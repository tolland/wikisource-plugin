# Syncing arbitrary page trees

Open **Page trees** in the viewer (`/page-trees`). This is separate from
proofread-index tracking: it includes the root page itself and all cached
slash-delimited descendants, with no dependency on an Index or backing scan.

For example, save a mapping from upstream
`The Principles of Psychology (James)` to local
`Book:The Principles of Psychology (James)`. A descendant
`The Principles of Psychology (James)/Chapter 1` then maps to
`Book:The Principles of Psychology (James)/Chapter 1`. The target root can
also have a completely different name. Nested paths remain intact. Titles
that merely start with the same text, without the separating slash, are excluded.

1. Choose two registered sites and enter the source and target root **titles**.
   Save the root mapping. This saves a root PageLink with PageTreeLink tracking;
   it does not assert that the revisions agree.
2. Choose **Fetch trees and counterparts**, then drain the queue from Fetch.
   Root requests discover subpages where the site's namespace supports them.
   The history depth applies to the discovered pages too. After first discovery,
   fetch again to check mapped counterpart titles that were not previously known.
3. Run the report. Review the exact source and target titles. Select rows and
   choose **Pair selected pages** to save the descendant PageLinks.
4. Inspect the matching anchor proposals. **Confirm selected anchors** asserts
   matching revision pairs; page pairing alone does not assert matching content.
   Existing page-pair drill-downs remain available for revision-level inspection.
5. Select writable rows and choose **Stage selected changes**. Open **Batches**
   to inspect the frozen revision-by-revision diffs. Push remains a separate
   action on each batch.

Reverse direction to compare or stage from the other site. The stored pairing
is symmetric, while reports and staging are directional. Source-only pages
cannot be staged until the mapped target has been fetched and confirmed absent.
Rows with no revisions on either side are omitted. Diverged and unlinked pages
are not writable; confirm an actual matching anchor or reconcile them through
the existing page-pair tools.

The mapping changes destination titles. It does not rewrite page bodies:
absolute links, template names, and ProofreadPage transclusion references retain
their stored text. Inspect these in batch diffs before pushing. Reports describe
the cache; refresh both trees to discover remote additions and current revisions.

The `pagetreelink` schema migration runs with normal backend database upgrades.
Root mappings and their page pairings are included in natural-key dumps.
