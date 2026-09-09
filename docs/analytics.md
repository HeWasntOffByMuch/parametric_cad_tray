# Usage analytics

One SQLite file, no third party, no cookies, no identifiers derived from
anything about the visitor's machine. It answers two questions: *is anyone
using this*, and *what are they building*.

The public answer to the first is a single number in the header of the app,
rendered like this and shown only once it is greater than zero:

> **1,204** custom molds generated

(An illustration of the string, not a reading. The counter starts at zero and
is never seeded.) This document is what that number means, where it lives, and
how to read everything behind it.

---

## 1. The public metric

**`custom_molds_generated` = the number of rows in `qualified_usages`.**

A row exists there for one `(session_id, config_hash)` pair, and only when all
four of these were true:

1. **The configuration is custom.** At least one geometry parameter differs
   from the default `Params()` *and* from every shipped preset. Renaming a
   design, switching preview/export quality, or choosing which halves to export
   are not geometry — those do not make a configuration custom.
2. **The build succeeded.** Enforced by the file having to exist: a failed
   export writes no artifact, so `cache.artifact_path()` returns nothing, the
   route 404s, and no recorder runs. There is no path from a failure to a count.
3. **An artifact was actually served.** Not requested, not generated —
   `record_download` is called after the file has been found on disk and is
   about to be streamed, so a 404 or a probe for a key that does not exist
   cannot inflate anything.
4. **The artifact is one someone takes away.** `step`, `stl` or `zip`. A `glb`
   is what the viewer renders in the browser; fetching it is not a download in
   any sense a counter should care about.

**One design is one usage.** Downloading `male.step`, `female.step`,
`male.stl`, `female.stl` and `bundle.zip` from a single session is **1**, not 5
— because `qualified_usages` declares:

```sql
UNIQUE(session_id, config_hash)
```

and the writer uses `INSERT OR IGNORE`. The deduplication is the database
constraint, not a Python check: two downloads arriving on different threads at
the same instant must not both be able to decide they are the first.

Three counters are public, all served by `GET /api/stats`:

| field | meaning |
|---|---|
| `custom_molds_generated` | rows in `qualified_usages` — the headline number |
| `unique_designs_downloaded` | distinct custom `config_hash` with a real download, across all sessions |
| `total_artifact_downloads` | every artifact served, including previews |

Only the first is shown in the UI. It is cached in-process for 45 seconds, so
a page load costs at most one `COUNT(*)` per 45 s no matter how many visitors
arrive at once.

### What cannot move it

- **A browser cannot.** `POST /api/analytics/event` accepts four event names
  and nothing else, and none of them writes to `qualified_usages`. The counter
  is reachable only from the artifact routes, server-side, after the bytes
  exist.
- **A preview cannot.** GLB is excluded by format, and a preview build is a
  different cache key anyway.
- **An untouched preset cannot.** `is_custom` is 0 for it.
- **A repeat cannot.** Same session, same configuration, any number of files:
  one row.
- **A missing session cannot.** An anonymous download (no `s=` parameter) still
  counts towards `unique_designs_downloaded`, but never invents a session id to
  create a usage.

None of it is seeded. The number starts at zero and the UI renders nothing at
all until it is greater than zero.

---

## 2. Privacy

### Not collected

Raw IP addresses, geolocation, names, email addresses, fingerprints, the full
user agent, complete referrer URLs, the contents of any generated STEP/STL/GLB,
and any text a user typed — including the design's own `name` field.

### Identifiers

Two random UUIDs from `crypto.randomUUID()`, nothing more:

| id | storage | lifetime |
|---|---|---|
| `visitor_id` | `localStorage` | until the browser's site data is cleared |
| `session_id` | `sessionStorage` | the tab |

They are **random**, never derived. Not from the IP, not from the user agent,
not from hardware, screen resolution, canvas, fonts or timezone. If storage is
unavailable — private mode, a sandboxed frame, storage disabled — the id is
transient and the visit simply counts as new. The server stores whatever
opaque string it is handed, truncated to 64 characters, and never inspects it.

There is no cookie, so there is nothing to consent to.

### Attribution

First-touch, captured once per session, and only ever the **hostname** of the
referrer:

```
https://makerworld.com/en/models/12345/leather-tray?from=search   ← what the browser sends
makerworld                                                        ← what is stored
```

The frontend sends only `document.referrer`'s *origin*; the server reduces that
to a hostname and maps it onto a small closed set (`makerworld`, `reddit`,
`youtube`, `printables`, `thingiverse`, `google`, `direct`, `other`, …). An
explicit `utm_source` wins over the referrer, because a campaign link says what
the campaign is while a referrer only says which page the browser came from.
`utm_medium` and `utm_campaign` are stored as given, bounded to 64 characters.

Navigating around inside the app does not rewrite where the visit came from:
`ensure_session` uses `INSERT OR IGNORE` and afterwards only touches
`last_seen_at`.

### Bots

Not fingerprinted, not blocked, not profiled. The metric's own definition does
most of the work: a crawler does not change a geometry parameter, wait for a
CAD build, and then fetch a STEP file with a session id it kept across two
requests.

---

## 3. Storage

A dedicated SQLite file, configured by `TRAYMOLD_ANALYTICS_DB`.

| environment | path | why |
|---|---|---|
| production | `/var/lib/traymold/analytics/analytics.sqlite3` | its own docker volume, `traymold_analytics` |
| development (`make dev`) | `<repo>/.cache/analytics/analytics.sqlite3` | gitignored, disposable |
| tests | a `tmp_path` per test | never touches a real database |
| anything else | **unset → analytics is off** | nothing writes a database into whatever directory a server happened to start in |

**It is never inside the artifact cache.** `TRAYAPI_CACHE_DIR` is swept every
five minutes on size and age; the analytics database is the record and is only
ever appended to. In the container they are two separate volumes mounted at two
separate paths, and the image creates both mount points owned by the app user
(uid 10001) so a fresh named volume inherits that ownership rather than root's.

Connection settings, applied on every connection:

```sql
PRAGMA journal_mode = WAL;      -- the stats reader never blocks a download writer
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 3000;     -- a brief overlap waits rather than raising
PRAGMA synchronous = NORMAL;    -- no fsync on the download path
```

One connection per thread (FastAPI runs sync endpoints in a threadpool). Every
transaction is a single `with conn:` block around one or two statements —
nothing holds a write lock across a file read or a CAD build. Timestamps are
UTC, ISO 8601, second resolution, stored as text so they sort lexically and
read without a tool.

### Migrations

`PRAGMA user_version`, and an ordered list of migrations in
`analytics/schema.py`. Append, never edit — an applied migration has already
run somewhere. `migrate()` is idempotent and runs on first connect, so there is
no init step to remember and no bootstrap table to create first.

---

## 4. Schema

```
sessions             one per browser tab
  session_id PK, visitor_id, first_seen_at, last_seen_at,
  source, medium, campaign, referrer_host, landing_path

designs              what a cache key was built from
  cache_key PK, config_hash, is_custom, quality, preset, profile_kind,
  tray_length_mm, tray_width_mm, tray_depth_mm,
  leather_thickness_mm, leather_compression, forming_gap_mm, created_at

analytics_events     the funnel, client and server
  id PK, event_type, session_id, created_at, config_hash, job_id,
  is_default, preset, tray_*_mm, leather_thickness_mm, forming_gap_mm,
  output_format, output_part, duration_ms, error_code, metadata

qualified_usages     THE PUBLIC COUNTER
  id PK, session_id → sessions, visitor_id, config_hash,
  first_download_at, source, preset, profile_kind, tray_*_mm,
  leather_thickness_mm, leather_compression, forming_gap_mm,
  UNIQUE(session_id, config_hash)

artifact_downloads   every file actually served
  id PK, session_id, visitor_id, config_hash, cache_key,
  artifact_name, format, part, is_custom, downloaded_at
```

`designs` exists because the artifact route is handed a cache key and nothing
else. Without that row a download could only be attributed by rebuilding the
geometry, which is not something analytics gets to do.

Only `qualified_usages` declares a foreign key. A download can arrive carrying
a session id this process never saw — a link opened in a new tab, a restarted
server — and dropping it would be worse than an unreferenced id. The counter is
the one place a dangling reference would be a real defect, so its writer
inserts a stub session first.

Indexes: `sessions(visitor_id | source | first_seen_at)`,
`designs(config_hash)`, `analytics_events(event_type, created_at)` and
`(session_id, event_type)`, `qualified_usages(source | config_hash |
first_download_at)`, `artifact_downloads(downloaded_at)` and `(config_hash,
is_custom)`.

---

## 5. Events

Four from the browser, seven from the server. The client list is a closed enum
on the Pydantic model, so an unknown name is a 422 and not a new row.

| event | from | when |
|---|---|---|
| `app_opened` | client | first render |
| `config_engaged` | client | the first parameter change, once per session |
| `share_link_copied` | client | the share button |
| `makerworld_clicked` | client | the outbound link (via `sendBeacon`, so it survives the navigation) |
| `preview_requested` / `preview_completed` / `preview_failed` | server | the job manager |
| `export_requested` / `export_completed` / `export_failed` | server | the job manager |
| `artifact_downloaded` | server | a qualifying artifact served |

`*_completed` carries `duration_ms`; `*_failed` carries the diagnostic code
(`E-MOLD-040`, `geometry_build_error`, …), which is what makes the failure-rate
line in the report worth reading.

Two attribution details worth knowing when reading the funnel:

- **A cache hit counts as a completed build, with no duration.** The artifact
  cache is content-addressed and long-lived, so a hit is the common path, and
  the visitor did get their preview — but nothing was built, and a 4 ms file
  read among the build times would turn the median into a measure of the cache
  hit rate. The route records the completion; the duration is `NULL`.
- **A deduplicated build is attributed to whoever asked first.** When two
  sessions request the same geometry at the same instant, the second attaches
  to the running job rather than starting a second one. Both get a
  `*_requested`; the single `*_completed` carries the first session's id.

---

## 6. HTTP surface

### `GET /api/stats`

Public. The three counters above, all integers, never negative.

```json
{"custom_molds_generated": 1204, "unique_designs_downloaded": 1187, "total_artifact_downloads": 5310}
```

If analytics is disabled, or the query fails, it returns zeros with a 200 — the
frontend renders nothing for a zero, so a broken database costs a decoration
and not a page.

### `POST /api/analytics/event`

204 always, even when rate limited or malformed after validation. Its own token
bucket (`TRAYAPI_ANALYTICS_RATE_LIMIT`, default 60/min per client), separate
from the build limiter, so telemetry can never starve a CAD job.

```json
{"event": "config_engaged", "session_id": "…", "visitor_id": "…",
 "source": "makerworld", "medium": "model", "campaign": "leather_tray",
 "referrer": "https://makerworld.com", "landing_path": "/parametric_cad_tray/"}
```

Every field is length-bounded on the model. **No event accepted here can move
`custom_molds_generated`.**

### There is no admin endpoint

Deliberately. This application has no authentication mechanism, and an internal
analytics summary reachable over HTTP with nothing in front of it is a worse
answer than a shell command on the host. The full report is the CLI below.

---

## 7. Operating it

Everything below assumes `cd ~/traymold` on the VPS.

```bash
# the full summary
docker compose --env-file .env exec api python -m trayapi.analytics.report

# locally, against the development database
make analytics

# any other file
python -m trayapi.analytics.report --db /path/to/analytics.sqlite3
```

### Check it is working

```bash
# is the path set in the running container?
docker compose --env-file .env exec api printenv TRAYMOLD_ANALYTICS_DB

# does the file exist, and how big is it?
docker compose --env-file .env exec api ls -la /var/lib/traymold/analytics/

# the public number, from outside
curl -s https://api.example.com/api/stats | python3 -m json.tool
```

A WAL database is three files: `analytics.sqlite3`, `-wal` and `-shm`. All
three are normal; the `-wal` is checkpointed back into the main file
automatically.

The deploy workflow checks all of this for you on every rollout, in the step
*"Check the analytics database is writable"*: it opens the database inside the
container,
writes a row and deletes it again. A read alone would not answer the question —
a volume that is read-only, or owned by root instead of uid 10001, opens fine
and fails on the first write. It reports a **warning**, never a failure: a
counter is not worth failing a deploy over. The public smoke cannot see any of
this, because analytics swallows its own errors by design.

### Size

Roughly 300 bytes per event and per download row. Ten thousand sessions that
each preview a few times and download once is on the order of 10 MB. This is
not a database that needs a retention policy for a long time; if it ever does,
`analytics_events` is the table to prune and `qualified_usages` is the one to
keep.

```bash
docker compose --env-file .env exec api \
  python -c "import os;print(os.path.getsize(os.environ['TRAYMOLD_ANALYTICS_DB'])/1e6,'MB')"
```

### Back it up

`sqlite3 .backup` is safe on a live database; copying the file while it is
being written to is not.

```bash
docker compose --env-file .env exec api python - <<'PY'
import os, sqlite3, datetime
src = sqlite3.connect(os.environ["TRAYMOLD_ANALYTICS_DB"])
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
dst = sqlite3.connect(f"/var/lib/traymold/analytics/backup-{stamp}.sqlite3")
with dst:
    src.backup(dst)
print("ok")
PY

# then off the host
docker run --rm -v traymold_analytics:/d -v "$PWD":/out alpine \
  sh -c 'cp /d/backup-*.sqlite3 /out/'
```

### Turn it off

Set the repository variable `TRAYMOLD_ANALYTICS_DB` to `off` and redeploy. That
is the durable answer — the deploy workflow rewrites `.env` on every rollout, so
an edit made on the host lasts until the next push:

```bash
# on the host, until the next deploy
grep -q '^TRAYMOLD_ANALYTICS_DB=' .env \
  && sed -i 's|^TRAYMOLD_ANALYTICS_DB=.*|TRAYMOLD_ANALYTICS_DB=|' .env \
  || echo 'TRAYMOLD_ANALYTICS_DB=' >> .env
docker compose --env-file .env up -d
```

An empty path disables analytics entirely: every recorder becomes a no-op,
`/api/stats` returns zeros, the counter disappears from the UI, and nothing
else in the application changes. The volume and its data are untouched.

### Failure isolation

Analytics cannot break the application. It is guarded three deep:

1. Each recorder runs inside `with session() as conn:`, which yields `None`
   rather than raising if the database is missing, locked or corrupt.
2. Every call site in `main.py` goes through `_safe()`, which swallows anything
   that escapes anyway.
3. The stats endpoint catches its own query failure and serves zeros.

There are tests for exactly this: a recorder monkeypatched to raise on every
call still leaves preview, export, download and validation working.

---

## 8. Reading it

### The CLI report

```
$ python -m trayapi.analytics.report

Visitors:                                142
Sessions:                                162
Engaged sessions:                        117
Successful previews:                     190
Exporting sessions:                       60
Downloading sessions:                     42
Qualified custom usages:                  40
Unique custom designs downloaded:         38
Artifact downloads:                      114
Returning visitors:                       20

Preview → download conversion:         38.2%
Engaged → download conversion:         35.9%
Build failure rate:                     8.2%
Median preview time:                    1.7s
Median export time:                     5.9s

Source (qualified usages):
  makerworld              10
  direct                  10
  reddit                   9
  printables               6
  youtube                  5

Sessions by source:
  makerworld              54
  reddit                  40
  direct                  32
  printables              24
  youtube                 12

Most common tray length:
  median 190 mm
  p25    180 mm
  p75    190 mm
Most common tray width:
  median 105 mm
  p25    100 mm
  p75    110 mm
Most common tray depth:
  median 31 mm
  p25    28 mm
  p75    31 mm
Most common leather thickness:
  median 2.4 mm
  p25    2 mm
  p75    3.2 mm
Most common forming gap:
  median 2.4 mm
  p25    2 mm
  p75    3.2 mm

Custom downloads:                        112
Default downloads:                         2
Share links copied:                        9
MakerWorld clicks out:                     9
```

(Synthetic traffic through the real recorders, so the shape is real and the
numbers are not anybody's.) Every figure is a SQL aggregate; the events table is
never read into Python.

Note `Qualified custom usages: 40` against `Unique custom designs downloaded:
38` — two visitors came back in a new session and rebuilt a design they had
already downloaded. That is two usages of one design, which is exactly what
those two lines are for.

### Straight SQL

```sql
-- the public number
SELECT COUNT(*) FROM qualified_usages;

-- growth, by month
SELECT substr(first_download_at, 1, 7) AS month, COUNT(*)
FROM qualified_usages GROUP BY month ORDER BY month;

-- where the people who actually finished came from
SELECT source, COUNT(*) AS usages
FROM qualified_usages GROUP BY source ORDER BY usages DESC;

-- what are they building: the shape of the demand
SELECT profile_kind, COUNT(*) AS n,
       ROUND(AVG(tray_length_mm), 1) AS avg_len,
       ROUND(AVG(tray_width_mm), 1)  AS avg_wid,
       ROUND(AVG(tray_depth_mm), 1)  AS avg_dep
FROM qualified_usages GROUP BY profile_kind ORDER BY n DESC;

-- which preset people start from, if any
SELECT COALESCE(preset, '(from scratch)') AS start, COUNT(*)
FROM qualified_usages GROUP BY start ORDER BY 2 DESC;

-- leather thickness, the number that decides the forming gap
SELECT leather_thickness_mm, COUNT(*) FROM qualified_usages
GROUP BY leather_thickness_mm ORDER BY 2 DESC;

-- what fails, and how often
SELECT error_code, COUNT(*) FROM analytics_events
WHERE event_type LIKE '%_failed' GROUP BY error_code ORDER BY 2 DESC;

-- how slow is slow
SELECT event_type, COUNT(*), MIN(duration_ms), MAX(duration_ms)
FROM analytics_events WHERE duration_ms IS NOT NULL GROUP BY event_type;

-- the drop-off, in one row
SELECT
  (SELECT COUNT(*) FROM sessions) AS sessions,
  (SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE event_type='config_engaged') AS engaged,
  (SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE event_type='export_requested') AS exported,
  (SELECT COUNT(DISTINCT session_id) FROM qualified_usages) AS downloaded;

-- STEP or STL: which way people take it away
SELECT format, COUNT(*) FROM artifact_downloads
WHERE format IN ('step','stl','zip') GROUP BY format ORDER BY 2 DESC;
```

---

## 9. Where the code is

```
packages/api/trayapi/analytics/
  __init__.py   the facade: what the rest of the API is allowed to call
  db.py         connections, PRAGMAs, migration, the never-raises session()
  schema.py     MIGRATIONS — append only
  custom.py     is_custom_configuration(), preset_name(), dimensions()
  sources.py    referrer hostname → a small closed set
  service.py    the recorders, and public_stats()
  report.py     the CLI

packages/web/src/analytics.ts              ids, first-touch attribution, track()
packages/web/src/panels/UsageCounter.tsx   the number in the header
packages/api/tests/test_analytics.py       52 tests, most about what must NOT count
packages/web/tests/analytics.test.ts       identity, attribution, engagement
```

The rule the module is built around, in one sentence:

> A qualified custom usage is one `(session, config_hash)` pair for which a
> genuinely custom configuration was built successfully and at least one of its
> exportable artifacts was actually served.
