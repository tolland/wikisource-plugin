# The cluster: services, ports, and which of them are local

What a running system is made of, which pieces are optional, and which of them
you are expected to supply yourself. There is no single "the cluster" — the same
five services are arranged three different ways depending on whether you are
running tests, running the docker stack, or working against real wikis on the
LAN. This page is the map of all three.

Port *conventions* are in `docs/reference/logging.md` §0 and `AGENTS.md`; this
page is about what actually runs, what talks to what, and where the conventions
and the compose defaults currently disagree.

## 1. The five services

| Service | What it is | Supplied by | Required? |
|---|---|---|---|
| **MediaWiki (primary)** | the wiki being read from — `upstream` in sync language | docker (`docker/mediawiki/`), or a real host | yes, at least one wiki |
| **MediaWiki (secondary)** | the second wiki of a sync pair — `local` | docker, `pair` profile | only for sync/promotion work |
| **wtbot** | the FastAPI sidecar: SQLite cache, VFS surface, fetch/commit workers | `uv run fastapi dev`, or docker `api` profile | yes |
| **viewer** | the SvelteKit debug UI over wtbot | `npm run dev`, or docker `api` profile | no — debugging and out-of-band approval only |
| **OCR** | a [py-ocrapi](https://github.com/tolland/py-ocrapi) / Wikimedia OCR instance | docker `ocr` profile, **or a host you already run** | no — the editor works without it; the "Run OCR" menu is empty |

Two things are deliberately *not* services here:

- **pix2tex** used to be its own container with its own client. It is now one
  `engine` value behind py-ocrapi's URL+crop+rotate contract, so the container
  belongs to that project's compose file, not this one.
- **The IntelliJ plugin** is not in any cluster. It is a client, and it reaches
  everything through wtbot — including scan bytes, which it fetches via
  `GET /reference-image` rather than from the wiki directly.

### Who talks to whom

```
IntelliJ plugin ─┐
                 ├─HTTP──▶ wtbot ──pywikibot──▶ MediaWiki (primary)
viewer ──────────┘          │     └────────────▶ MediaWiki (secondary)
                            │
                            └─HTTP──▶ OCR service ──fetches image URL──▶ MediaWiki
```

The arrow that surprises people is the last one. A `wikimedia`-kind OCR backend
is **URL-driven**: wtbot hands it an image *URL* and the OCR service fetches the
image itself. So the OCR host must be able to reach the wiki host — which is why
`docker/wikimedia-ocr/env.local` carries an `APP_IMAGE_HOSTS` allow-list, and
why the wtbot container runs `network_mode: host` (so the URLs it mints are the
same ones a browser would use, with no docker-internal-to-published port
remapping).

## 2. Three deployment topologies

### 2a. Pure docker cluster (`compose.seeded.yml`)

Everything in containers, ports in the **1857x** range. This is the persistent
stack — the one you leave running.

```bash
# the wiki pair
docker compose -f compose.seeded.yml --profile pair up -d --wait

# ...plus wtbot and the viewer over HTTP
docker compose -f compose.seeded.yml -f compose.wtbot.yml \
    --profile pair --profile api up -d --wait

# ...plus a containerised OCR instance
docker compose -f compose.seeded.yml --profile ocr up -d wikimedia-ocr
```

| Port | Service | Set by |
|---|---|---|
| 18571 | MediaWiki primary | `WIKISOURCE_PORT` |
| 18572 | MediaWiki local (pair) | `WIKISOURCE_LOCAL_PORT` |
| 18573 | viewer | `WTBOT_VIEWER_PORT` |
| 18574 | wtbot API | `WTBOT_PORT` |
| 18575 | wikimedia-ocr | `WIKIMEDIA_OCR_PORT` |

Notes that matter in practice:

- **`compose.seeded.yml` restores a prebuilt database volume** (`seed-restore`
  copies the external `wikisource_mediawiki-db-seed` volume in) rather than
  installing MediaWiki from scratch. That external volume comes from
  `compose.build.yml`; without it, use `compose.yml` instead.
- **Both wikis seed from the same anchor** (`SEED_DUMPS` / `SEED_SCANS`), so the
  pair starts *converged*. Blank them for bare wikis:
  `SEED_DUMPS= SEED_SCANS= docker compose … up -d --wait`.
- **`MW_SERVER` is baked into `LocalSettings.php` at install time**, so a volume
  installed for one port must never be reused on another. That is why the pair
  runs under its own `COMPOSE_PROJECT_NAME`.
- **`--wait` is only trustworthy** because the healthcheck requires a marker
  written *after* seeding; the extension check alone goes green while an import
  is still running.
- **wtbot's SQLite is disposable.** `WTBOT_RESET_DB=1` empties it without
  rebuilding the wikis, which are the slow half.

### 2b. Dev machine alongside IntelliJ (1856x)

wtbot and the viewer run from source on the workstation; the wikis are wherever
you point them (LAN hosts, or the docker stack above).

```bash
uv run fastapi dev src-py/wtbot/main.py --port 18564
cd viewer && npm run dev        # 18563, /api proxied to 18564
```

| Port | Service | Where the default lives |
|---|---|---|
| 18561 | *(reserved)* local MediaWiki | — |
| 18562 | *(reserved)* alternate MediaWiki | — |
| 18563 | viewer | `viewer/vite.config.ts` |
| 18564 | wtbot API | `WtbotAppSettings.DEFAULT_BASE_URL`, `wtbot/cli/deps.py` |
| 18565 | *(reserved)* wikimedia-ocr | — |

The plugin's sidecar is chosen per launch, so one session can point at the
docker stack and the next at the workstation sidecar:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew runIde \
    -PwtbotBaseUrl=http://127.0.0.1:18574
```

and a running IDE can be moved from Settings → Tools → WTBot without a restart
(see `docs/done/wtbot-base-url-switching.md`).

### 2c. Workstation + LAN services ("prod-ish")

The layout in real use: **the wikis and OCR are hosts, not containers**, and
only wtbot (and optionally the viewer) runs on the dev machine. An OCR instance
hosted on a hypervisor rather than in docker is the normal case here, not a
special one — nothing in wtbot cares where a backend lives, only that its
`base_url` is reachable and that it can in turn reach the wiki that hosts the
scans.

```
workstation                    LAN
  IntelliJ + plugin
  wtbot (18564)   ─────────▶  https://wikisource-debian-13.lan/w/api.php
  viewer (18563)  ─────────▶  https://en.wikisource.org/w/api.php
                  ─────────▶  https://ocr.wikisource-debian-13.lan
```

Two configuration items are specific to this topology:

- **CA bundle.** A LAN wiki with a private CA needs `WTBOT_WIKI_CA_BUNDLE`
  pointing at it (`docker/certs/LPL-CA.crt` is the one this project uses). This
  is exactly why the preview is proxied through wtbot rather than called from
  Kotlin: the JVM never needs the wiki in its trust store.
- **Reachability is transitive.** The LAN OCR host must resolve and reach the
  wiki host, because it fetches the scan itself. An OCR service that works from
  your desk but returns nothing in the editor is almost always this.

Sites are registered per wiki and addressed by `label` thereafter — nothing
creates one implicitly, and a site with no credential is refused at fetch time:

```bash
uv run wtbot site add --label local --family mywikisource --code en \
    --api-url https://wikisource-debian-13.lan/w/api.php \
    --username Admin --password ... [--bot-password-suffix wtbot]
```

OCR backends are registered separately, scoped by a plain string (wtbot passes
the site's `family/code`), so a backend needs no `Site` row to exist:

```
OcrBackendConfig(scope=…, name="wmocr", kind="wikimedia",
                 base_url="https://ocr.wikisource-debian-13.lan",
                 default_engine="tesseract")
```

`kind` selects the wire protocol: `wikimedia` (URL-driven, server-side
crop/rotate — py-ocrapi, covering tesseract, Google Vision and pix2tex) or
`token_api` (bytes-driven, bearer token, prompt-capable). `tesseract` is the
default engine because it is the free one.

### 2d. Test stacks (1858x)

pytest spins its own compose project so it cannot collide with a running
cluster. Driven by `src-py/tests/wiki_harness/stack.py`, and reachable by hand
through the same code path:

```bash
PYTHONPATH=src-py/tests uv run python -m wiki_harness up [--api] [--rebuild]
PYTHONPATH=src-py/tests uv run python -m wiki_harness status
PYTHONPATH=src-py/tests uv run python -m wiki_harness down
```

| Port | Service | Constant |
|---|---|---|
| 18581 | MediaWiki upstream | `PAIR_UPSTREAM_PORT` |
| 18582 | MediaWiki local | `PAIR_LOCAL_PORT` |
| 18583 | wtbot API (with `--api`) | `PAIR_WTBOT_PORT` |

Overridable via `SYNC_UPSTREAM_PORT` / `SYNC_LOCAL_PORT` / `SYNC_WTBOT_PORT`,
under `SYNC_COMPOSE_PROJECT_NAME` (default `wtbot-sync-pair`). The harness
deliberately uses different env names from `WIKISOURCE_PORT`, so overriding the
single-instance fixture cannot silently move the pair onto a colliding port.

Two harness details worth knowing: `upstream` is addressed as `127.0.0.1` and
`local` as `localhost` because pywikibot's cookie jar is scoped by hostname and
not by port — same interface, two names, two sessions. And `local` burns a few
revision ids at seed time (`SEED_REVID_BURN`), so the two wikis never assign the
same revid to the same page; a bug comparing revids across sites would otherwise
pass in the fixture and fail against real wikis.

By default wiki access in tests is faked in-memory (`FakeWikiClient`); the
docker-backed suites are `@pytest.mark.slow` and need `--runslow` plus a docker
daemon.

## 3. The compose files

| File | Base or overlay | What it is |
|---|---|---|
| `compose.yml` | base | two independent MediaWiki stacks installed from scratch, plus the `ocr` profile. The original fixture. |
| `compose.seeded.yml` | base | the same pair, but restoring a prebuilt DB volume instead of installing. What the harness and the persistent cluster use. |
| `compose.build.yml` | base | builds the seed volume (`wikisource_mediawiki-db-seed`) the file above consumes. |
| `compose.wtbot.yml` | overlay | wtbot + viewer, `api` profile. Overlays either base. |
| `compose.principles.yml` | overlay | swaps the seed content for the Hertz *Principles* fixtures (`principles_remote.xml` / `principles_local.xml`, djvu + pdf scans). |

Profiles: `pair` (second wiki), `api` (wtbot + viewer), `ocr` (wikimedia-ocr).
Nothing but the primary wiki starts without a profile.

`compose.wtbot.yml` is an overlay rather than a copy in each base because the
two bases already duplicate the MediaWiki services, and that is the part that
drifts.

## 4. Known port discrepancies

Recorded rather than silently reconciled, because each is a decision someone
should make deliberately:

- **`AGENTS.md` assigns 18583 to the viewer in the test range; the code uses it
  for wtbot** (`PAIR_WTBOT_PORT`). The test range in `AGENTS.md` (18581 wiki,
  18582 wiki, 18583 viewer, 18584 wtbot, 18585 OCR) is one service out of step
  with `wiki_harness/stack.py` from 18583 on. The harness never starts a viewer,
  so nothing collides today.
- **`CLAUDE.md`'s `runIde` example points at 18584** and calls it "the docker
  harness", but the harness's wtbot default is 18583 and the persistent
  cluster's is 18574. The example works only if you set `SYNC_WTBOT_PORT=18584`.
- **`compose.yml` defaults are pre-convention**: `WIKISOURCE_PORT` 8080,
  `WIKIMEDIA_OCR_PORT` 8090 — while its `WIKISOURCE_LOCAL_PORT` is already
  18582, which is the *test* range.
- **`compose.build.yml` defaults `WIKISOURCE_PORT` to 18575**, which is the OCR
  slot in both the convention and `compose.seeded.yml`. Building the seed volume
  while an OCR container is up will fail to bind.

Until these are reconciled, set the port env vars explicitly rather than relying
on a file's default.
</content>
