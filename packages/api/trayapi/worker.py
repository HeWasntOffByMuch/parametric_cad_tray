"""Process isolation for geometry builds.

CadQuery/OCC must not run in the FastAPI process: a bad boolean can abort the
interpreter, and OCC leaks steadily.  This is a small pool of persistent child
processes rather than a `ProcessPoolExecutor` because we need three things that
the executor does not give:

* a **real timeout** - the ability to terminate the one worker running a
  runaway build, without taking down the other in-flight jobs;
* **cancellation** of work already running, for the same reason;
* **pre-warming** - importing traymold costs 3.1 s, so a cold worker per request
  would dominate a 2.5 s preview.

Each worker is `spawn`ed, imports traymold once, then serves builds over a
duplex pipe until it is recycled.
"""

from __future__ import annotations

import logging
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Any

from .errors import CANCELLED, PUBLIC_MESSAGE, TIMEOUT, WORKER_CRASH
from .settings import SETTINGS

log = logging.getLogger("trayapi.worker")


# --------------------------------------------------------------------------
# parent side
# --------------------------------------------------------------------------
class WorkerFailure(RuntimeError):
    def __init__(self, kind: str, message: str, diagnostics: list[dict] | None = None):
        self.kind = kind
        self.message = message
        self.diagnostics = diagnostics or []
        super().__init__(f"{kind}: {message}")


@dataclass
class _Worker:
    process: subprocess.Popen
    conn: Any
    listener: Any
    socket_path: str
    tasks: int = 0

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def kill(self) -> None:
        if self.alive:
            self.process.kill()
        try:
            self.process.wait(timeout=5.0)
        except Exception:  # pragma: no cover
            pass
        self._cleanup()

    def close(self) -> None:
        try:
            self.conn.send(None)
        except Exception:
            pass
        try:
            self.process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3.0)
        self._cleanup()

    def _cleanup(self) -> None:
        for closeable in (self.conn, self.listener):
            try:
                closeable.close()
            except Exception:  # pragma: no cover
                pass
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass


class WorkerPool:
    def __init__(
        self,
        size: int | None = None,
        paths: tuple[str, ...] | None = None,
        module: str = "trayapi.worker_main",
        extra_paths: tuple[str, ...] = (),
        start_timeout: float | None = None,
        max_tasks: int | None = None,
    ):
        self.size = size or SETTINGS.workers
        self.paths = tuple(paths or _default_paths()) + tuple(extra_paths)
        self.start_timeout = start_timeout or SETTINGS.worker_start_timeout_s
        #: builds before a worker is retired.  OCC leaks steadily, so workers are
        #: replaced rather than trusted to stay healthy indefinitely.
        self.max_tasks = max_tasks or SETTINGS.max_tasks_per_worker
        #: the worker program.  Tests point this at a fault-injecting module to
        #: exercise crash, hang and exception handling without corrupting a real
        #: build; production never changes it.
        self.module = module
        self._idle: queue.Queue[_Worker] = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._spawned = 0
        for _ in range(self.size):
            self._idle.put(self._spawn())

    # -- lifecycle ---------------------------------------------------------
    def _spawn(self) -> _Worker:
        socket_path = str(Path(tempfile.mkdtemp(prefix="trayapi-")) / "w.sock")
        authkey = secrets.token_bytes(32)
        listener = Listener(socket_path, family="AF_UNIX", authkey=authkey)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([*self.paths, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        proc = subprocess.Popen(
            [sys.executable, "-m", self.module, socket_path, authkey.hex()],
            env=env,
        )
        self._spawned += 1
        conn = _accept(listener, self.start_timeout)
        worker = _Worker(process=proc, conn=conn, listener=listener, socket_path=socket_path)
        if conn is None or not conn.poll(self.start_timeout):
            worker.kill()
            raise RuntimeError("worker did not start within its budget")
        hello = conn.recv()
        if not hello.get("ready"):
            worker.kill()
            raise RuntimeError(f"worker could not import the geometry core: {hello.get('detail', '')[:300]}")
        return worker

    def shutdown(self) -> None:
        self._closed = True
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                return

    @property
    def spawned(self) -> int:
        return self._spawned

    @property
    def idle_count(self) -> int:
        return self._idle.qsize()

    # -- work --------------------------------------------------------------
    def run(
        self,
        payload: dict,
        *,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
        poll_interval: float = 0.05,
    ) -> dict:
        """Run one build in one worker.  Blocking; call from a thread.

        Raises `WorkerFailure` for every failure mode, so the caller never sees a
        raw OCC exception.
        """
        if self._closed:
            raise WorkerFailure(WORKER_CRASH, "the worker pool is shut down")
        timeout = SETTINGS.build_timeout_s if timeout is None else timeout
        worker = self._idle.get()
        recycle = False
        try:
            worker.conn.send(payload)
            deadline = time.monotonic() + timeout
            while True:
                if cancel is not None and cancel.is_set():
                    recycle = True
                    raise WorkerFailure(CANCELLED, PUBLIC_MESSAGE[CANCELLED])
                if not worker.alive:
                    recycle = True
                    raise WorkerFailure(WORKER_CRASH, PUBLIC_MESSAGE[WORKER_CRASH])
                if worker.conn.poll(poll_interval):
                    break
                if time.monotonic() > deadline:
                    recycle = True
                    raise WorkerFailure(TIMEOUT, PUBLIC_MESSAGE[TIMEOUT])
            try:
                result = worker.conn.recv()
            except EOFError:
                recycle = True
                raise WorkerFailure(WORKER_CRASH, PUBLIC_MESSAGE[WORKER_CRASH]) from None
            worker.tasks += 1
            if not result.get("ok"):
                raise WorkerFailure(result["kind"], result["message"], result.get("diagnostics"))
            return result["report"]
        finally:
            if recycle or not worker.alive or worker.tasks >= self.max_tasks:
                self._retire(worker)
            else:
                self._idle.put(worker)

    def _retire(self, worker: _Worker) -> None:
        try:
            worker.kill()
        except Exception:  # pragma: no cover
            log.exception("failed to terminate worker")
        if not self._closed:
            try:
                self._idle.put(self._spawn())
            except Exception:  # pragma: no cover
                log.exception("failed to respawn worker")


def _accept(listener, timeout: float):
    """`Listener.accept()` with a deadline: a worker that dies before connecting
    must not hang the pool."""
    holder: dict[str, Any] = {}

    def run():
        try:
            holder["conn"] = listener.accept()
        except Exception as exc:  # pragma: no cover
            holder["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    return holder.get("conn")


def _default_paths() -> tuple[str, ...]:
    packages = Path(__file__).resolve().parents[2]
    return (str(packages / "tray-core"), str(packages / "api"))


_POOL: WorkerPool | None = None
_POOL_LOCK = threading.Lock()


def get_pool() -> WorkerPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = WorkerPool()
        return _POOL


def shutdown_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown()
            _POOL = None
