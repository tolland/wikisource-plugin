# Work outlines in the IDE

Not built. How the plugin could present a work's structure (parts, chapters,
sections) and printed page labels when navigating its scans.

The outline model itself — PDF/EPUB extraction, the editable YAML transclusion
proposal, labels and the proposed navigation read model — is wtbot's and is
described in the wtbot repository (`../wtbot`,
`docs/internal/design/work-outlines.md`; the implemented CLI is in
`docs/operations/transclusion-generation.md`).

## Goal

A work with hundreds of scans should be navigable by part, chapter, section
and printed page label where known, while every scan stays reachable at its
existing address. Missing structure must never block transcription or
navigation.

## What the plugin needs from wtbot

A versioned, per-Index navigation read model, fetched in batches or lazily for
large works:

- Index identity, structure availability and a revision token that changes
  when either the effective pagelist or the stored structure changes;
- ordered outline nodes with stable opaque IDs, titles, optional type/number
  and mapped scan extents;
- scan entries: scan number, canonical Page path, effective printed label with
  confidence/provenance, and the outline nodes it belongs to (a scan at a
  shared boundary can belong to several).

Reads come from cached data and must not trigger extraction or wiki fetches
per row.

## Presentation

- A **flat labelled view** of an Index's pages, e.g. `32 — p. 9`, available
  whenever a pagelist exists, with or without an outline. Unknown labels show
  the scan number.
- An optional **structured view** grouping the same rows, e.g.
  Part 1 → Chapter 1 → Section 1, showing the source's full depth regardless
  of how deep transclusion pages were generated.
- Opening any row resolves through `WtWikiFiles` to the existing canonical
  Page file. Labels and grouping nodes are browser presentation
  (`WikiBrowserNode`-style), never VirtualFiles: they must not rename files,
  change URLs, create wiki directories or change save targets.
- Fall back to the plain `@pages` list when structure is absent, stale or
  switched off. Cache presentation per revision token.
- Missing local copies of pages stay visible in the structure rather than
  disappearing.

## Checks when built

Grouped and flat views open the same file ID and save target; a pagelist label
change invalidates the view; missing cached pages remain represented.
