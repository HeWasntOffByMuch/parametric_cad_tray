# The API image: FastAPI, the geometry core, and the OpenCascade runtime it needs.
#
# Built from the repository root, not from deploy/:
#     docker build -f deploy/Dockerfile -t traymold-api .
#
# Two stages, because pip's build machinery is about as large as the OCP wheel
# itself and none of it is needed to serve requests.

# ---------------------------------------------------------------- builder ---
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY deploy/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ---------------------------------------------------------------- runtime ---
FROM python:3.11-slim-bookworm

# Everything `import OCP` links against that the wheel does not vendor. It
# vendors its own OCC, VTK, freetype and image codecs; what is left is GL and
# X11, which libgl1 and libx11-6 supply (the latter pulls libxcb, libXau,
# libXdmcp, libbsd and libmd along with it). curl is here for HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libx11-6 libexpat1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/packages/tray-core:/app/packages/api" \
    PYTHONUNBUFFERED=1 \
    TRAYAPI_CACHE_DIR=/var/lib/traymold/artifacts

WORKDIR /app
COPY packages/tray-core/traymold /app/packages/tray-core/traymold
COPY packages/api/trayapi /app/packages/api/trayapi

# Byte-compile ahead of time. A worker imports the whole geometry core on start
# and is recycled every TRAYAPI_MAX_TASKS_PER_WORKER builds, so this cost would
# otherwise be paid over and over on a read-only-ish container.
RUN python -m compileall -q /app/packages >/dev/null

# Not root. The pool spawns subprocesses and writes STEP/STL/GLB into the cache
# volume; neither needs privileges.
RUN useradd --system --uid 10001 --create-home --home-dir /home/traymold traymold \
    && mkdir -p /var/lib/traymold/artifacts \
    && chown -R traymold:traymold /var/lib/traymold /app

USER traymold

# Import once here so a missing system library fails the build rather than the
# first request of the first deployment.
RUN python -c "import traymold.mold, trayapi.main; print('imports ok')"

EXPOSE 8000

# start-period covers the worker pool pre-warm: the lifespan hook imports the
# geometry core in every worker before the first request, ~4 s cold.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health >/dev/null || exit 1

# One uvicorn process, deliberately. Job state, the SSE subscriber lists and the
# worker pool all live in it, and a second process would answer
# GET /api/jobs/{id} for jobs it has never heard of. Scale CAD throughput with
# TRAYAPI_WORKERS, which adds subprocesses inside this process's pool.
CMD ["uvicorn", "trayapi.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--timeout-graceful-shutdown", "20"]
