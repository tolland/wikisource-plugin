# VCR cassettes

This directory holds YAML cassettes for `test_vcr_fetch.py`.  Each cassette captures
all HTTP traffic (MediaWiki action API + file download) for one test function, so the
tests can run fully offline once recorded.

## Directory layout

```
cassettes/
  en_ws/     # en.wikisource.org responses
  lan/       # local wikisource-debian-13.lan responses
```

## Recording

Run against the real wikis from a machine that can reach both:

```bash
# Record / refresh all cassettes (overwrites existing):
VCR_RECORD_MODE=all uv run pytest src-py/tests/test_vcr_fetch.py -v

# Record only new cassettes, keep existing ones:
VCR_RECORD_MODE=new_episodes uv run pytest src-py/tests/test_vcr_fetch.py -v

# For the LAN wiki you also need the CA bundle:
WTBOT_WIKI_CA_BUNDLE=/path/to/ca.crt VCR_RECORD_MODE=all \
  uv run pytest src-py/tests/test_vcr_fetch.py -v -k lan
```

## Playback (default)

```bash
uv run pytest src-py/tests/test_vcr_fetch.py -v
```

Tests without a cassette are **skipped** (not failed), so CI works before the first
recording commit.

## What is recorded / what is stubbed

- All MediaWiki **action API** calls (JSON) are recorded faithfully.
- **Binary file downloads** (the DjVu/PDF blob) are replaced with a `<BINARY_STUB>`
  sentinel in the cassette so YAML stays small.  The real blob lives at
  `src-py/tests/fixtures/Tractatus.djvu` (committed separately via Git LFS or as a
  symlink to your local copy — see `conftest.py` for the path env var).
- Auth headers (`Authorization`, `Cookie`, `Set-Cookie`) are stripped.
- `User-Agent` is normalized to `wtbot-test/1`.
