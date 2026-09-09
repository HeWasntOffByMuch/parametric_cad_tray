#!/usr/bin/env bash
# Exercise a running stack the way the browser application does.
#
#   deploy/smoke.sh                        # the local rehearsal
#   deploy/smoke.sh https://api.example.com
#   ORIGIN=https://user.github.io deploy/smoke.sh https://api.example.com
#
# Every check is one the deployment can plausibly fail on its own: TLS, the
# proxy buffering the event stream, CORS refusing the real frontend origin, the
# cache volume not persisting. Geometry correctness is the test suites' job, not
# this script's.
set -uo pipefail

BASE="${1:-http://localhost:8080}"
ORIGIN="${ORIGIN:-http://localhost:4173}"
BASE="${BASE%/}"

pass=0; fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; fail=$((fail+1)); }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

jget() { python3 -c 'import json,sys;d=json.load(sys.stdin)
for k in sys.argv[1].split("."):
    d = d[int(k)] if isinstance(d, list) else d.get(k)
    if d is None: break
print("" if d is None else d)' "$1" 2>/dev/null; }

need() { command -v "$1" >/dev/null || { echo "smoke.sh needs $1"; exit 2; }; }
need curl; need python3

printf '\033[1mtraymold deployment smoke\033[0m  %s\n  origin %s\n' "$BASE" "$ORIGIN"

# --- reachability -----------------------------------------------------------
step "reachability"
health="$(curl -fsS --max-time 15 "$BASE/api/health" 2>&1)"
if [ -z "$health" ] || [ "$(printf %s "$health" | jget status)" != "ok" ]; then
  bad "GET /api/health" "$health"
  echo; echo "The API is not answering. Nothing below can pass; stopping."
  exit 1
fi
ok "GET /api/health -> ok"

workers_started="$(printf %s "$health" | jget workers.started)"
[ "${workers_started:-0}" -ge 1 ] \
  && ok "worker pool pre-warmed (${workers_started} started)" \
  || bad "worker pool did not pre-warm" "workers: $(printf %s "$health" | jget workers)"

ver="$(curl -fsS --max-time 15 "$BASE/api/version")"
cq="$(printf %s "$ver" | jget cadquery)"; ocp="$(printf %s "$ver" | jget OCP)"
[ "$cq" = "2.8.0" ] && ok "CadQuery $cq / OCP $ocp (the verified pair)" \
  || bad "unexpected geometry runtime" "cadquery=$cq OCP=$ocp - the cache key and the 2.4 um verification are tied to 2.8.0"

# TLS only matters when the deployment claims it.
case "$BASE" in
  https://*)
    curl -fsS --max-time 15 "$BASE/api/health" >/dev/null 2>&1 \
      && ok "TLS certificate verifies" || bad "TLS certificate does not verify";;
  *) ;;
esac

# --- the contract the browser depends on ------------------------------------
step "schema and presets"
schema="$(curl -fsS --max-time 20 "$BASE/api/schema")"
[ -n "$(printf %s "$schema" | jget json_schema.title)$(printf %s "$schema" | jget schema_version)" ] \
  && ok "GET /api/schema carries json_schema, defaults and ui_hints" \
  || bad "GET /api/schema is not the expected shape"

presets="$(curl -fsS --max-time 20 "$BASE/api/presets")"
p0="$(printf %s "$presets" | jget 0.name)"
[ -n "$p0" ] && ok "GET /api/presets -> first preset '$p0'" || bad "GET /api/presets returned nothing"

params="$(printf %s "$presets" | python3 -c 'import json,sys;print(json.dumps(json.load(sys.stdin)[0]["params"]))')"
[ -n "$params" ] || { bad "could not read preset parameters"; params='{}'; }

step "validation"
valid="$(curl -fsS --max-time 20 -X POST "$BASE/api/validate" \
          -H 'content-type: application/json' -d "{\"params\":$params}")"
[ "$(printf %s "$valid" | jget valid)" = "True" ] \
  && ok "POST /api/validate accepts the preset" \
  || bad "the preset does not validate" "$valid"
hash1="$(printf %s "$valid" | jget params_hash)"
[ -n "$hash1" ] && ok "params_hash $hash1" || bad "no params_hash"

bogus="$(printf %s "$params" | python3 -c 'import json,sys;p=json.load(sys.stdin);p.setdefault("leather",{})["thickness"]=-5;print(json.dumps(p))')"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST "$BASE/api/validate" \
         -H 'content-type: application/json' -d "{\"params\":$bogus}")"
[ "$code" = "422" ] && ok "a negative leather thickness is rejected (422)" \
  || bad "invalid parameters were not rejected" "got HTTP $code"

# --- public exposure --------------------------------------------------------
step "public exposure"
cors="$(curl -s -i --max-time 20 -X OPTIONS "$BASE/api/preview" \
         -H "Origin: $ORIGIN" -H 'Access-Control-Request-Method: POST' \
         -H 'Access-Control-Request-Headers: content-type' \
        | tr -d '\r' | grep -i '^access-control-allow-origin:' | head -1)"
if printf %s "$cors" | grep -qi "$ORIGIN"; then
  ok "CORS preflight allows $ORIGIN"
else
  bad "CORS preflight does not allow $ORIGIN" "${cors:-no access-control-allow-origin header} - check TRAYAPI_ALLOWED_ORIGINS"
fi

evil="$(curl -s -i --max-time 20 -X OPTIONS "$BASE/api/preview" \
         -H 'Origin: https://not-your-frontend.example' -H 'Access-Control-Request-Method: POST' \
        | tr -d '\r' | grep -ci 'access-control-allow-origin: https://not-your-frontend.example')"
[ "$evil" = "0" ] && ok "an unlisted origin is refused" \
  || bad "any origin is allowed" "TRAYAPI_ALLOWED_ORIGINS is probably still '*'"

big="$(python3 -c 'print("{\"params\":{\"name\":\"" + "x"*400000 + "\"}}")')"
code="$(printf %s "$big" | curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST \
         "$BASE/api/validate" -H 'content-type: application/json' --data-binary @-)"
case "$code" in
  413) ok "an oversized body is rejected (413)";;
  *)   bad "an oversized body was not rejected" "got HTTP $code";;
esac

# --- a real build, watched over SSE -----------------------------------------
# The SSE check below can only see a build that actually runs, and the artifact
# cache is content-addressed and survives redeploys - so the preset's own
# preview is usually already there, arrives complete in one frame, and the
# buffering check fails for a reason that has nothing to do with the proxy.
# Nudging one dimension by under a millimetre guarantees a real build to watch.
# The export further down deliberately keeps the untouched preset, so nothing
# here can look like a custom mold to the usage counter.
preview_params="$(printf %s "$params" | python3 -c 'import json,sys,time
d = json.load(sys.stdin)
try:
    profile = d["tray"]["profile"]
    profile["length"] = round(profile["length"] + (int(time.time()) % 1000) * 0.001, 3)
except Exception:
    pass                      # an unexpected shape falls back to the preset
print(json.dumps(d))' 2>/dev/null)"
[ -n "$preview_params" ] || preview_params="$params"
# A jitter the core would reject is worse than no jitter at all. A 422 makes
# curl fail, which empties the response and falls back just the same.
checked="$(curl -fsS --max-time 20 -X POST "$BASE/api/validate" \
            -H 'content-type: application/json' -d "{\"params\":$preview_params}" 2>/dev/null)"
[ "$(printf %s "$checked" | jget valid)" = "True" ] || preview_params="$params"

step "preview build"
job="$(curl -fsS --max-time 30 -X POST "$BASE/api/preview" \
        -H 'content-type: application/json' -d "{\"params\":$preview_params}")"
job_id="$(printf %s "$job" | jget id)"
if [ -z "$job_id" ]; then
  bad "POST /api/preview did not return a job" "$job"
else
  ok "POST /api/preview -> $job_id"

  # The point of this check is the proxy, not the build: if Caddy buffers the
  # stream, terminal events arrive only when the connection closes and the
  # elapsed time below jumps to the whole build.
  sse="$(mktemp)"; t0=$(date +%s)
  curl -N -sS --max-time 180 "$BASE/api/jobs/$job_id/events" > "$sse" 2>/dev/null &
  curl_pid=$!
  for _ in $(seq 1 180); do
    grep -q '^event: \(complete\|failed\|cancelled\)$' "$sse" && break
    kill -0 "$curl_pid" 2>/dev/null || break
    sleep 1
  done
  kill "$curl_pid" 2>/dev/null; wait "$curl_pid" 2>/dev/null
  elapsed=$(( $(date +%s) - t0 ))

  if grep -q '^event: complete$' "$sse"; then
    ok "the event stream reported completion in ${elapsed}s"
  else
    bad "no completion event on the stream" "$(head -c 400 "$sse")"
  fi
  if [ "$(printf %s "$job" | jget cached)" = "True" ]; then
    # Nothing ran, so there was no intermediate state to emit. Not a pass and
    # not a failure: the proxy was not exercised.
    printf '  \033[33mskip\033[0m  buffering check: this preview was served from cache\n'
  else
    grep -q '^event: running$' "$sse" \
      && ok "intermediate 'running' event arrived before it (the proxy is not buffering)" \
      || bad "no intermediate event: the proxy is buffering the stream" "check flush_interval -1 in the Caddyfile"
  fi
  rm -f "$sse"

  final="$(curl -fsS --max-time 20 "$BASE/api/jobs/$job_id")"
  state="$(printf %s "$final" | jget state)"
  [ "$state" = "complete" ] && ok "job state complete" || bad "job state $state" "$(printf %s "$final" | jget error)"

  glb_url="$(printf %s "$final" | jget artifacts.preview.url)"
  [ -n "$glb_url" ] || glb_url="$(printf %s "$final" | python3 -c 'import json,sys
a=json.load(sys.stdin).get("artifacts",{})
g=[v["url"] for v in a.values() if v.get("format")=="glb"]
print(g[0] if g else "")' 2>/dev/null)"

  if [ -n "$glb_url" ]; then
    glb="$(mktemp)"
    if curl -fsS --max-time 60 "$BASE$glb_url" -o "$glb"; then
      size=$(wc -c < "$glb")
      python3 - "$glb" <<'PY' && ok "GLB $((size/1024)) kB, magic ok, male and female are separate nodes" || bad "the GLB is not the expected shape"
import json, struct, sys
raw = open(sys.argv[1], "rb").read()
assert raw[:4] == b"glTF", "not a GLB"
n = struct.unpack("<I", raw[12:16])[0]
doc = json.loads(raw[20:20 + n])
names = {x.get("name", "") for x in doc.get("nodes", [])}
assert any("male" in s.lower() for s in names), names
assert any("female" in s.lower() for s in names), names
PY
    else
      bad "could not download the GLB" "$BASE$glb_url"
    fi
    rm -f "$glb"
  else
    bad "the completed job carried no GLB artifact"
  fi
fi

# --- the cache --------------------------------------------------------------
step "artifact cache"
t0=$(python3 -c 'import time;print(time.time())')
again="$(curl -fsS --max-time 30 -X POST "$BASE/api/preview" \
          -H 'content-type: application/json' -d "{\"params\":$preview_params}")"
ms="$(python3 -c "import sys;print(round((__import__('time').time()-$t0)*1000))")"
if [ "$(printf %s "$again" | jget cached)" = "True" ]; then
  ok "the identical request was served from cache in ${ms} ms"
else
  bad "an identical request rebuilt instead of hitting the cache" \
      "state=$(printf %s "$again" | jget state) - is the artifacts volume mounted?"
fi

# Read before the download below, compared after it. The only thing this script
# ever *downloads* is the untouched preset's export, which must never count as a
# custom mold; the jittered preview above is a GLB, which never counts either.
before="$(curl -fsS --max-time 15 "$BASE/api/stats" 2>/dev/null | jget custom_molds_generated)"

step "export"
exp="$(curl -fsS --max-time 30 -X POST "$BASE/api/export" \
        -H 'content-type: application/json' -d "{\"params\":$params}")"
exp_id="$(printf %s "$exp" | jget id)"
if [ -z "$exp_id" ]; then
  bad "POST /api/export did not return a job" "$exp"
else
  for _ in $(seq 1 180); do
    exp="$(curl -fsS --max-time 20 "$BASE/api/jobs/$exp_id")"
    case "$(printf %s "$exp" | jget state)" in complete|failed|cancelled) break;; esac
    sleep 2
  done
  if [ "$(printf %s "$exp" | jget state)" = "complete" ]; then
    formats="$(printf %s "$exp" | python3 -c 'import json,sys;print(",".join(sorted({v["format"] for v in json.load(sys.stdin).get("artifacts",{}).values()})))')"
    ok "export complete, formats: $formats"
    bundle="$(printf %s "$exp" | jget bundle_url)"
    if [ -n "$bundle" ]; then
      bytes=$(curl -fsS --max-time 120 "$BASE$bundle" -o /dev/null -w '%{size_download}')
      [ "${bytes:-0}" -gt 1000 ] && ok "bundle.zip downloads ($((bytes/1024)) kB)" \
        || bad "bundle.zip is implausibly small" "$bytes bytes"
    else
      bad "no bundle_url on the completed export"
    fi
  else
    bad "the export job did not complete" "$(printf %s "$exp" | jget error)"
  fi
fi

# --- usage analytics --------------------------------------------------------
# Read-only on purpose. Analytics is isolated from failure by design, so an
# unwritable database is deliberately invisible from out here - the deploy
# workflow checks that on the host, where it can actually be seen. What this
# proves is that the endpoint answers with the shape the frontend reads, and
# that the preset this script just downloaded did not move the public counter.
step "usage analytics"
stats="$(curl -fsS --max-time 15 "$BASE/api/stats" 2>&1)"
after="$(printf %s "$stats" | jget custom_molds_generated)"
if printf %s "$stats" | python3 -c 'import json,sys
d = json.load(sys.stdin)
keys = ("custom_molds_generated", "unique_designs_downloaded", "total_artifact_downloads")
assert all(isinstance(d.get(k), int) and d[k] >= 0 for k in keys), d' 2>/dev/null; then
  ok "GET /api/stats -> three counters (${after:-?} custom molds)"
else
  bad "GET /api/stats is not the shape the frontend reads" "$stats"
fi

if [ -n "${before:-}" ] && [ -n "${after:-}" ]; then
  [ "$before" = "$after" ] \
    && ok "an untouched preset download did not move the counter" \
    || bad "the public counter moved for a preset download" "$before -> $after"
fi

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
