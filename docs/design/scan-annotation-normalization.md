# Migrating scan annotations to normalized coordinates

The SQLite model stores `normalized_x`, `normalized_y`, `normalized_width`,
and `normalized_height`. These are fractions of the complete page raster.
The `/pages/annotations` API retains the names `x`, `y`, `width`, and `height`,
but their units are now fractions, **not pixels**. Deploy the updated plugin
and backend together; stop the service and close annotation editors during
migration. The canvas and OCR crops still use decoded-image pixels, with
conversion at the persistence boundary.

Normalization supports different resolutions of the same page bounds and
orientation. It does not register annotations against a cropped or replacement
scan. First-class image identity and persisted rendition dimensions remain
separate work in `scan-image-modeling.md`.

## Existing databases

Run these commands from the repository root, separately for each database.
Use the annotation JSON dump from that same database. Back up the complete
SQLite database (including anchors and links) and retain cached images first.
The application automatically upgrades on startup, so do not restart it until
the backfill and final migration have completed.

```bash
export WTBOT_DATABASE_URL=sqlite:////absolute/path/database.db
uv run alembic upgrade a21d6430c901

# Dry run: validate the dump against current rows and inspect actual images.
uv run python src-py/scripts/normalize_scan_annotations.py \
  /absolute/path/database.db /absolute/path/out.json \
  --blob-root /absolute/path/blob_root > normalization-preview.json

# Write only normalized geometry; retain pixel columns and all row identities.
uv run python src-py/scripts/normalize_scan_annotations.py \
  /absolute/path/database.db /absolute/path/out.json \
  --blob-root /absolute/path/blob_root --apply > normalization-report.json

uv run alembic upgrade head
```

The staging migration adds nullable columns. The one-off loop decodes one
reference image per annotated page with Pillow, then fills the normalized
columns in one transaction. It prefers `{page_pk}-src` cached bytes and falls
back to `source_image_url or thumb_url`. It does not trust `thumb_width` or
ProofreadPage's `size` field. The report records dimensions, SHA-256 and the
location used. Network fetching uses the backend's configured CA bundle.

This assumes the default reference rendition is still the one used to draw
the boxes. If the original was fetched at another width, or the remote image
has changed, recover its original bytes before backfilling. The script rejects
boxes outside the measured image but cannot detect every mismatched image.

Missing URLs, invalid images, out-of-bounds boxes, duplicate dump IDs, or rows
whose identity/geometry differs from the dump abort before any updates.
Rows absent from the dump remain unconverted. The final migration refuses
incomplete/invalid geometry, then removes the pixel columns and makes the
normalized columns nonnullable. IDs, labels, timestamps, anchors, and box links
are preserved. Repeating the backfill at the staging revision is safe with the
same image bytes. No network access occurs inside Alembic migrations.

Fresh databases upgrade straight to head. Downgrading a populated normalized
database requires restoring the backup: original pixel dimensions cannot be
reconstructed from normalized coordinates alone.
