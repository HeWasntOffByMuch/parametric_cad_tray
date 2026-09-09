# Deployment

Two halves, deployed independently on a push to `main`:

| | where | workflow | trigger paths |
|---|---|---|---|
| the browser application | GitHub Pages | `.github/workflows/pages.yml` | `packages/web/**` |
| the API and its CAD workers | your VPS, in Docker, behind Caddy | `.github/workflows/api.yml` | `packages/api/**`, `packages/tray-core/**`, `deploy/**` |

They are separate because they have nothing in common operationally: the
frontend is a few hundred kB of static files that any CDN will serve, and the
API is a 2 GB image that spawns OpenCascade subprocesses. The only thing joining
them is a URL and a CORS list.

---

## 1. Rehearse it locally first

Everything below runs on your machine before any of it touches the VPS. The
image, the compose file and the Caddyfile are the same files; the only
differences live in `deploy/.env.local` — no TLS, unprivileged ports, and the
image built from your checkout instead of pulled from GHCR.

```bash
make deploy-local      # build, start, wait for healthy       (~5 min cold)
make deploy-smoke      # 19 checks against http://localhost:8080
make deploy-local-web  # the Pages build, pointed at that stack, on :4173
make deploy-logs       # follow both containers
make deploy-down       # stop and remove
```

`make deploy-local` needs a running Docker daemon and about 4 GB of free disk;
the OCP wheel alone is around 400 MB and unpacks to several times that.

The first build is slow because it downloads and installs CadQuery and OCP.
Later builds reuse the layer unless `deploy/requirements.txt` changes.

### What the smoke script checks

`deploy/smoke.sh` deliberately tests the things a *deployment* gets wrong, not
the things a geometry change gets wrong — the 249 tests already cover the
latter. In order:

| check | what it would catch |
|---|---|
| `/api/health` answers, workers pre-warmed | the container starts but the pool never spawns |
| CadQuery 2.8.0 / OCP 7.9.3 | an unpinned rebuild moved the geometry runtime |
| TLS verifies (when the URL is https) | the certificate is missing, self-signed or for the wrong name |
| `/api/schema`, `/api/presets` | the image shipped without the geometry core on `PYTHONPATH` |
| the preset validates; a negative thickness is a 422 | the core is importable but broken |
| CORS allows your frontend origin | `TRAYAPI_ALLOWED_ORIGINS` is wrong — the most common failure |
| CORS refuses an unlisted origin | it is still `*` |
| a 400 kB body is a 413 | the request-size ceiling is not in effect |
| a preview completes, watched over SSE | the whole path works end to end |
| a `running` event arrives *before* `complete` | **the proxy is buffering the stream** |
| the GLB parses, with male and female as separate nodes | the preview would render as one unselectable blob |
| an identical request comes back `cached` in milliseconds | the artifacts volume is not mounted, so nothing persists |
| an export produces STEP and STL, and `bundle.zip` downloads | large binary responses survive the proxy |

The SSE ordering check is the one worth understanding. If Caddy buffers the
event stream, every event still arrives — just all at once, when the connection
closes. The build would appear to take its full duration with no sign of life,
which is exactly the behaviour the endpoint exists to avoid. `flush_interval -1`
in the `Caddyfile` prevents it, and this check is what proves it.

### Checking the pieces without Docker

```bash
make deploy-check    # compose files parse; caddy validate on the Caddyfile
```

---

## 2. What runs on the VPS

Two shapes, chosen by the `TRAYMOLD_PROXY` repository variable. Which one you
want is decided by a single question: **does anything already own port 80 on
this host?**

### `caddy` (default) — nothing else is on 80/443

```
                    :80 / :443
                        |
                    [ caddy ]  automatic HTTPS, compression, body ceiling
                        |      flush_interval -1 on /api/jobs/*/events
                    127.0.0.1:8000
                        |
                    [ api ]    one uvicorn process
                        |      TRAYAPI_WORKERS CAD subprocesses inside it
                  /var/lib/traymold/artifacts   (named volume)
```

### `external` — something else already owns them

```
      :443  [ your nginx / Caddy / Traefik ]   your certificate, your config
                        |
                    127.0.0.1:8000
                        |
                    [ api ]
                  /var/lib/traymold/artifacts
```

In both, the API binds `TRAYMOLD_API_BIND`, loopback by default, so it is never
reachable from the internet without a proxy in front of it. The compose stack is
the same file either way; `--profile caddy` is what starts the bundled proxy,
and the deploy workflow passes it or not according to `TRAYMOLD_PROXY`.

---

## 2a. Behind a proxy you already run

Set the `TRAYMOLD_PROXY` repository variable to `external`. `TRAYMOLD_SITE_ADDRESS`
and `TRAYMOLD_TLS_EMAIL` stop mattering — the certificate is not ours to get.
`TRAYAPI_ALLOWED_ORIGINS` still matters exactly as much, because CORS is enforced
in the API, not the proxy.

**One thing will not work by default, in every proxy:** job state streams as
server-sent events, and a proxy that buffers still delivers every event — just
all at once, when the connection closes. A 2.5 s build then shows no sign of
life until it is over, which is the behaviour the endpoint exists to avoid.
`deploy/smoke.sh` asserts an intermediate event arrives before the terminal one,
so it catches this; the configs below prevent it.

### nginx

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;
    # ... your existing ssl_certificate / ssl_certificate_key ...

    # A regex location beats a prefix one in nginx, so this wins for the event
    # stream and the block below handles everything else.
    location ~ ^/api/jobs/[^/]+/events$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;      # without these three the stream is held
        proxy_cache off;          # until the job finishes and the
        gzip off;                 # connection closes
        proxy_read_timeout 300s;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;  # an export is seconds of CAD, not milliseconds
        client_max_body_size 1m;
    }
}
```

### An existing Caddy

Add a site block; this is the bundled `deploy/Caddyfile` with the container
address swapped for the host one.

```caddyfile
api.example.com {
    @sse path_regexp sse ^/api/jobs/[^/]+/events$
    @compressible not path_regexp sse ^/api/jobs/[^/]+/events$
    encode @compressible zstd gzip

    handle @sse {
        reverse_proxy 127.0.0.1:8000 {
            flush_interval -1
        }
    }
    handle /api/* {
        request_body {
            max_size 256KB
        }
        reverse_proxy 127.0.0.1:8000
    }
}
```

### Traefik

Traefik reaches containers over a docker network rather than the host, so also
attach the `api` service to Traefik's network in a compose override, then route
to it on port 8000. Traefik does not buffer responses by default, so SSE works
without extra configuration — but verify it with `deploy/smoke.sh` rather than
assuming.

After wiring any of them up, prove it end to end from your machine:

```bash
ORIGIN=https://hewasntoffbymuch.github.io ./deploy/smoke.sh https://api.example.com
```

---

**One uvicorn process, deliberately.** Job state, the SSE subscriber lists and
the worker pool all live in the process. A second one would answer
`GET /api/jobs/{id}` for jobs it has never heard of, and would open a second SSE
stream that never fires. Scale CAD throughput with `TRAYAPI_WORKERS`, which adds
subprocesses *inside* the pool; scale beyond one host only with sticky sessions
by job id and a shared cache, which is not built.

Sizing: each worker holds an OCC session and peaks around 500 MB during a
boolean. Two workers on a 2-core / 4 GB VPS is comfortable; the compose file caps
the container at `TRAYMOLD_MEMORY_LIMIT` (3 GB) so a pathological parameter set
takes out the container rather than the host.

---

## 3. VPS prerequisites

1. **Docker Engine with the compose plugin.**
   ```bash
   curl -fsSL https://get.docker.com | sh
   docker compose version    # v2.17 or newer: the deploy uses --wait-timeout
   ```
2. **A deploy user in the `docker` group**, with your CI public key in
   `~/.ssh/authorized_keys`.
   ```bash
   sudo adduser --disabled-password --gecos "" deploy
   sudo usermod -aG docker deploy
   ```
3. **DNS**: an `A` (and `AAAA`, if you have one) record for your API hostname
   pointing at the VPS. In `caddy` mode Caddy gets a certificate for exactly that
   name on first start, so it must resolve *before* the first deploy or the run
   will sit waiting for a certificate it cannot obtain.
4. **Ports 80 and 443 free, and open.** Port 80 is not optional in `caddy` mode:
   the ACME HTTP challenge uses it.

   Check before the first deploy — something else holding them is the most
   common first-deploy failure, and it surfaces as
   `Bind for 0.0.0.0:80 failed: port is already allocated`:
   ```bash
   sudo ss -lptn 'sport = :80 or sport = :443'
   ```
   If anything is listening, use `external` mode instead (§2a) rather than
   trying to move it.
5. Nothing else. The workflow creates `~/traymold` in the deploy user's home and
   puts the compose file, the Caddyfile and the `.env` there itself. The
   repository is never cloned on the VPS, and no source ships in the image beyond
   the two Python packages.

   `/opt/traymold` is the conventional place for a service like this, and the
   workflow will use it — but it is root-owned and the deploy user is
   deliberately not in sudoers, so it has to be handed over once by hand:
   ```bash
   sudo mkdir -p /opt/traymold && sudo chown deploy:deploy /opt/traymold
   ```
   then set the `VPS_APP_DIR` variable to `/opt/traymold`. The home directory
   default needs none of that, which is why it is the default.

### The SSH key

Generate a key used for nothing else:

```bash
ssh-keygen -t ed25519 -C "traymold deploy" -f ~/.ssh/traymold_deploy -N ""
ssh-copy-id -i ~/.ssh/traymold_deploy.pub deploy@your.vps
cat ~/.ssh/traymold_deploy        # -> the VPS_SSH_KEY secret, whole file
ssh-keyscan your.vps              # -> the VPS_SSH_HOST_KEY variable
```

`VPS_SSH_HOST_KEY` is optional but worth setting: without it the workflow falls
back to `ssh-keyscan` at deploy time, which trusts whatever answers.

---

## 4. GitHub configuration

**Settings → Secrets and variables → Actions.**

### Secrets

| name | value |
|---|---|
| `VPS_HOST` | hostname or IP of the VPS |
| `VPS_USER` | the deploy user, e.g. `deploy` |
| `VPS_SSH_KEY` | the private key, the entire file including both delimiter lines |
| `VPS_PORT` | optional, if sshd is not on 22 |

`GITHUB_TOKEN` is provided automatically and is what both the workflow and the
VPS use to authenticate to GHCR — no personal access token is needed, and no
long-lived registry credential is stored on the host.

### Variables

| name | example | used by |
|---|---|---|
| `TRAYMOLD_API_DOMAIN` | `api.example.com` | both workflows |
| `TRAYMOLD_PROXY` | `caddy` (default) or `external` — see §2 | api |
| `TRAYMOLD_TLS_EMAIL` | `you@example.com` — required in `caddy` mode, ignored in `external` | api |
| `TRAYAPI_ALLOWED_ORIGINS` | `https://hewasntoffbymuch.github.io` | api |
| `VPS_SSH_HOST_KEY` | output of `ssh-keyscan` | api |
| `VPS_APP_DIR` | defaults to `~/traymold` in the deploy user's home; set it only for a path you have already chowned to that user | api |
| `TRAYAPI_WORKERS` | defaults to `2` | api |
| `TRAYMOLD_MEMORY_LIMIT` | defaults to `3g` | api |
| `TRAYMOLD_API_BIND` | defaults to `127.0.0.1:8000`; change the port if something else on the host has it | api |
| `TRAYMOLD_API_BASE_URL` | only if the API is not plain https on `TRAYMOLD_API_DOMAIN` | pages |

The frontend build takes its API URL from `TRAYMOLD_API_BASE_URL` if set and
otherwise from `https://$TRAYMOLD_API_DOMAIN`, so the host is normally
configured once.

`TRAYAPI_ALLOWED_ORIGINS` must be the **exact** origin the browser sends: scheme
and host, no path, no trailing slash. For a project page that is
`https://<user>.github.io` — not `https://<user>.github.io/parametric_cad_tray`.

### Also enable

- **Settings → Pages → Source: GitHub Actions.**
- **Settings → Environments → `production`** (optional). The deploy job targets
  it, so adding a required reviewer there turns every API deploy into a manual
  approval.

---

## 5. What a deploy does

`.github/workflows/api.yml`, on a push to `main`:

1. **test** — the core and API suites, on the same pinned versions the image is
   built from, so a suite that passes here passes for the same reasons in the
   container.
2. **build** — buildx builds `deploy/Dockerfile` and pushes two tags to
   `ghcr.io/<owner>/<repo>/api`: `latest` and the commit SHA. Layers are cached
   in the Actions cache, which matters: the OCP wheel is 400 MB.
3. **deploy** — checks the configuration is complete and fails with a list if it
   is not; ships `deploy/` to the VPS over ssh as a tar stream; writes `.env`
   from the secrets and variables; then `docker compose pull` and
   `up -d --wait`, which blocks until the healthcheck passes.
4. **smoke** — `deploy/smoke.sh` against the live public URL. A deploy that
   comes up but answers wrongly fails the run.

A pull request touching the same paths runs **test** and builds the image to
prove the Dockerfile still works, and pushes and deploys nothing.

The `.env` pins `TRAYMOLD_IMAGE` to the commit SHA, not to `latest`, so the VPS
runs exactly what that run built.

### Rolling back

Re-run the deploy job of an earlier successful workflow run: it writes that
run's SHA into `.env` and restarts. Images are pruned after a week, so within
that window nothing needs rebuilding. To pin by hand:

```bash
ssh deploy@your.vps
cd ~/traymold          # or $VPS_APP_DIR, if you set one
sed -i 's|/api:.*|/api:<sha>|' .env
docker compose --env-file .env up -d --wait
```

---

## 6. Operating it

```bash
# In caddy mode add --profile caddy to anything that starts or stops containers;
# ps and logs do not need it.
cd ~/traymold
docker compose --env-file .env ps            # what is running
docker compose --env-file .env logs -f api   # the API, uvicorn and job records
docker compose --env-file .env logs -f caddy # requests, and ACME (caddy mode)
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool   # on the VPS
curl -s https://api.example.com/api/health | python3 -m json.tool # from outside
```

`/api/health` reports the worker pool (configured, started, idle), the cache
(entries, bytes, last sweep) and the rate limiter (clients, in flight). It runs
no geometry and touches no worker, so it is safe to poll from an uptime monitor.

The artifact cache is content-addressed and self-limiting: a background sweep
every 5 minutes drops entries past `TRAYAPI_CACHE_MAX_BYTES` (least recently
read first) or `TRAYAPI_CACHE_MAX_AGE_S`. It lives in the `traymold_artifacts`
volume, so a redeploy keeps every previously built design and serves it in
milliseconds. Clearing it is safe and costs only rebuild time:

```bash
docker compose --env-file .env down
docker volume rm traymold_artifacts
```

### When something is wrong

| symptom | look at |
|---|---|
| the browser reports a CORS error | `TRAYAPI_ALLOWED_ORIGINS` — the exact origin, no trailing slash |
| `Bind for 0.0.0.0:80 failed: port is already allocated` | another service owns 80/443; switch `TRAYMOLD_PROXY` to `external` and front the API with it (§2a) |
| Caddy loops on ACME | DNS does not resolve to this host yet, or port 80 is closed |
| a preview sits with no progress, then finishes all at once | the proxy is buffering: `flush_interval -1` on the SSE route |
| `429` on ordinary use | `TRAYAPI_RATE_LIMIT_REQUESTS`; note that cache hits and deduplicated attaches consume no concurrency slot, so a low limit here is a real limit |
| the container restarts under load | `TRAYMOLD_MEMORY_LIMIT`, or fewer `TRAYAPI_WORKERS` |
| every request rebuilds | the artifacts volume is not mounted; check `docker compose config` |

---

## 7. Upgrading the geometry runtime

`deploy/requirements.txt` pins CadQuery and OCP exactly, and
`traymold.api.environment()` reports both into the artifact cache key. An
upgrade therefore invalidates every cached build and can move the geometry, so
it is a code change with a test run behind it: edit the pin, let the suites run,
and re-verify against the reference STEP before merging. It is never something a
rebuild should do on its own.
