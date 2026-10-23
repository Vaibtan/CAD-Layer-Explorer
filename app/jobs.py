"""One bounded execution loop for disposable PDF child processes."""
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from .models import JobError, JobKind, JobRecord, NormalizedRender, error_adapter
from .repository import Repository
from .settings import LIMITS


class JobSupervisor:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository
        self._active: tuple[JobRecord, subprocess.Popen[bytes]] | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, digest: str, kind: JobKind, request: NormalizedRender | None = None,
                key: str | None = None) -> str:
        return self._repository.enqueue(digest, kind, request, key, LIMITS["queue"])

    def close(self) -> None:
        self._stop.set()
        with self._repository.lock:
            if self._active:
                self._kill(self._active[1])
        self._thread.join(timeout=5)

    def cancel_document(self, digest: str) -> None:
        """Called under the shared lifecycle lock before removing stored work."""
        if self._active and self._active[0]["document"] == digest:
            self._kill(self._active[1])
            self._active = None

    @staticmethod
    def _kill(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        if sys.platform != "win32":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            try:
                for child in psutil.Process(proc.pid).children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                proc.kill()
            except (psutil.NoSuchProcess, ProcessLookupError):
                pass
        proc.wait()

    def _cleanup(self, job: JobRecord) -> None:
        try:
            self._repository.cleanup_job_files(job["id"])
        except OSError:
            # A leftover temporary file must not stop all subsequent PDF work.
            # Restart cleanup removes it; published results remain authoritative.
            pass

    def _run(self) -> None:
        while not self._stop.wait(0.1):
            repository = self._repository
            with repository.lock:
                try:
                    job = repository.next_job()
                except sqlite3.Error:
                    continue
                if job is None:
                    continue
                target = repository.temp / f"{job['id']}.out"
                payload = repository.temp / f"{job['id']}.input"
                try:
                    payload.write_text(job["payload"])
                    proc: subprocess.Popen[bytes] = subprocess.Popen(
                        [sys.executable, "-m", "app.worker", str(payload), str(target)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=os.name == "posix")
                    self._active = (job, proc)
                    repository.update_job(job, "running")
                except (OSError, sqlite3.Error):
                    if self._active:
                        self._kill(self._active[1])
                        self._active = None
                    try:
                        repository.update_job(job, "failed", {
                            "code": "storage_failure", "message": "Could not start PDF work. Check local storage and retry."})
                    except sqlite3.Error:
                        pass
                    self._cleanup(job)
                    continue
            error = self._monitor(job, proc)
            with repository.lock:
                try:
                    if self._stop.is_set():
                        self._kill(proc)
                    elif repository.current_generation(job):
                        self._finish(job, proc, target, error)
                except (OSError, sqlite3.Error, ValueError):
                    # A malformed artifact or transient storage error belongs to
                    # this job; it must never take down the only execution loop.
                    try:
                        repository.update_job(job, "failed", {
                            "code": "storage_failure", "message": "Could not publish result. Free disk space and retry."})
                    except sqlite3.Error:
                        pass
                finally:
                    self._active = None
                    self._cleanup(job)

    def _monitor(self, job: JobRecord, proc: subprocess.Popen[bytes]) -> JobError | None:
        start = time.monotonic()
        timeout = LIMITS["analysis_seconds"] if job["kind"] == "analysis" else LIMITS["render_seconds"]
        error: JobError | None = None
        while proc.poll() is None and not self._stop.wait(0.05):
            if time.monotonic() - start > timeout:
                error = {"code": "timeout", "message": f"PDF job exceeded {timeout} seconds. Retry or use a smaller PDF."}
            try:
                processes = [psutil.Process(proc.pid)]
                processes += processes[0].children(recursive=True)
                if sum(process.memory_info().rss for process in processes) > LIMITS["memory_bytes"]:
                    error = {"code": "memory_limit", "message": "PDF child exceeded its memory budget."}
            except psutil.Error:
                pass
            if error:
                self._kill(proc)
                break
        return error

    def _finish(self, job: JobRecord, proc: subprocess.Popen[bytes], target: Path,
                error: JobError | None) -> None:
        if not error and proc.returncode != 0:
            diagnostic = target.with_suffix(".error")
            fallback: JobError = {
                "code": "worker_failed", "message": "PDF child exited unexpectedly (possibly a resource limit). Retry the operation."}
            try:
                error = error_adapter.validate_json(diagnostic.read_text()) if diagnostic.exists() else fallback
            except ValueError:
                error = fallback
        if not error:
            self._repository.publish(job, target)
        self._repository.update_job(job, "failed" if error else "succeeded", error)
