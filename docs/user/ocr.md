# OCR

OCR runs on a region of a page scan in the
[proofread page editor](proofread-editors.md). The recognised text is shown
for review first; nothing changes in your transcription until you apply it.

OCR services are configured per wiki in wtbot (see the wtbot repository,
`../wtbot`, `docs/reference/ocr.md`). The plugin discovers which backends and
engines the page's wiki offers; if there are none, the menu says so.

## Running OCR on a box

1. Draw a bounding box around the region on the reference scan.
2. Right-click the box and open **Run OCR**.
3. Choose an entry. The request runs in the background and the result opens
   in the **Wikisource OCR** tool window (bottom).

The **Run OCR** menu lists your favourites (below) that the page's wiki can
actually run. If none match — no favourites yet, or they all name a backend
this wiki doesn't have — it lists each configured backend on its own defaults
instead. **Configure Favourites…** at the bottom opens the settings page.

Right after a page opens the backend list may still be loading; the menu shows
"No OCR backends configured" until it arrives, and is correct on the next
right-click.

## Reviewing the result

Each result in the **Wikisource OCR** tool window shows the backend, engine and
page it came from, with the text in an editable area.

- **Apply to Linked Range** replaces the text range linked to the box with the
  (possibly edited) text. It is available only when the box is linked to a
  text range; it targets the range's current position, so edits made since the
  OCR ran are respected.
- **Copy** copies the text to the clipboard.

Applied text becomes an ordinary unsaved edit in the page editor.

## Favourites

**Settings → Tools → OCR Favourites** holds a short, ordered list of the
engine and language combinations you actually use. Each favourite has:

| Field | Required | Meaning |
|---|---|---|
| Engine | yes | e.g. `tesseract`, `google`, `pix2tex` |
| Backend | no | pin to one configured backend; blank uses the wiki's first backend |
| Languages | no | language codes to run with; blank uses the backend's defaults (what engines without languages, such as `pix2tex`, need) |
| Menu label | no | text shown in the Run OCR menu |
| Prompt | no | sent to the engine; ignored by engines that don't read one |

The engine and language pickers are filled from what the last opened page
editor discovered, and also accept free text.

There are two lists. The **application defaults** apply to every project.
Ticking **Use project-specific favourites** gives the current project its own
list instead (which may be deliberately empty). The page edits whichever list
is in effect for the project, so what you see is what the menu will use.

A favourite pinned to a backend that a wiki doesn't offer is simply left out
of that wiki's menu.
