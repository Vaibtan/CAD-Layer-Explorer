"""SQLite and filesystem persistence for document work.

The repository has no execution thread and never starts or kills PDF processes.
Its lock is shared by document work and the supervisor for atomic lifecycle
operations, including the generation check before publishing a child result.
"""
import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .models import (
    AnalysisManifest, AnalysisProfile, DocumentRecord, DocumentStatus, JobError,
    JobKind, JobRecord, JobState, NormalizedRender, WorkerJob,
    document_adapter, error_adapter, job_adapter, manifest_adapter, progress_adapter,
)
from .pdf import profile
from .settings import DATA, LIMITS


class StoreError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


class Repository:
    def __init__(self, root: str | Path = DATA) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.profile: AnalysisProfile = profile()
        self.db = sqlite3.connect(self.root / "state.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, generation TEXT, filename TEXT, size INTEGER);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, document TEXT, generation TEXT, kind TEXT,
            state TEXT, payload TEXT, error TEXT, sequence INTEGER);
          UPDATE jobs SET state='interrupted', error='{"code":"interrupted","message":"Application restarted. Retry this operation."}'
            WHERE state IN ('running','queued');
        """)
        self.db.commit()
        self.temp = self.root / "tmp"
        if self.temp.exists():
            shutil.rmtree(self.temp)
        self.temp.mkdir()

    def close(self) -> None:
        self.db.close()

    def row(self, digest: str) -> DocumentRecord:
        row: sqlite3.Row | None = self.db.execute("SELECT * FROM documents WHERE id=?", (digest,)).fetchone()
        if row is None:
            raise StoreError(404, "document_missing", "Document was not found.")
        return document_adapter.validate_python(dict(row))

    def list_documents(self) -> list[DocumentStatus]:
        with self.lock:
            rows: list[sqlite3.Row] = self.db.execute("SELECT * FROM documents ORDER BY rowid DESC").fetchall()
            return [self.status(document_adapter.validate_python(dict(row))["id"]) for row in rows]

    def render_job(self, key: str) -> JobRecord | None:
        with self.lock:
            row: sqlite3.Row | None = self.db.execute("SELECT * FROM jobs WHERE id=? AND kind='render'", (key,)).fetchone()
            return job_adapter.validate_python(dict(row)) if row is not None else None

    def directory(self, digest: str) -> Path:
        # Filesystem callers use IDs already validated against persisted records.
        return self.root / digest

    def manifest(self, digest: str) -> Path:
        self.row(digest)
        if not self.compatible(digest):
            raise StoreError(409, "analysis_not_ready", "Analysis is not ready. Check status or retry analysis.")
        return self.directory(digest) / "analysis.json"

    def read_manifest(self, digest: str) -> AnalysisManifest:
        return manifest_adapter.validate_json(self.manifest(digest).read_bytes())

    def compatible(self, digest: str) -> bool:
        path = self.directory(digest) / "analysis.json"
        try:
            stored = manifest_adapter.validate_json(path.read_bytes())
            return (stored["schema_version"] == self.profile["schema_version"]
                    and stored["analyzer_version"] == self.profile["analyzer_version"]
                    and stored["engines"] == self.profile["engines"]
                    and stored["settings"] == self.profile["settings"])
        except (OSError, ValueError):
            return False

    def enqueue(self, digest: str, kind: JobKind, request: NormalizedRender | None,
                key: str | None, capacity: int) -> str:
        """Persist a deduplicated job while enforcing the supervisor's capacity."""
        with self.lock:
            document = self.row(digest)
            job_id = key or f"{digest}-analysis-{document['generation']}"
            source = str(self.directory(digest) / "source.pdf")
            payload: WorkerJob
            if kind == "analysis":
                if request is not None:
                    raise ValueError("Analysis jobs cannot contain render requests.")
                payload = {"document": digest, "kind": "analysis", "source": source, "request": None}
            else:
                if request is None:
                    raise ValueError("Render jobs require a render request.")
                payload = {"document": digest, "kind": "render", "source": source, "request": request}
            old_row: sqlite3.Row | None = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            old = job_adapter.validate_python(dict(old_row)) if old_row is not None else None
            if old and old["state"] in ("queued", "running"):
                return job_id
            waiting = int(self.db.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0])
            if waiting >= capacity:
                raise StoreError(429, "queue_full", f"PDF queue is full ({capacity} waiting jobs). Retry shortly.")
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?)", (
                job_id, digest, document["generation"], kind, "queued", json.dumps(payload), None, time.time_ns()))
            self.db.commit()
            return job_id

    def retain(self, temp: Path, digest: str, filename: str, size: int) -> None:
        with self.lock:
            old = self.db.execute("SELECT id FROM documents WHERE id=?", (digest,)).fetchone()
            if old:
                temp.unlink(missing_ok=True)
                return
            directory = self.directory(digest)
            directory.mkdir(exist_ok=True)
            try:
                temp.replace(directory / "source.pdf")
                self.db.execute("INSERT INTO documents VALUES(?,?,?,?)", (digest, uuid.uuid4().hex, filename, size))
                self.db.commit()
            except Exception:
                self.db.rollback()
                shutil.rmtree(directory, ignore_errors=True)
                raise

    def status(self, digest: str) -> DocumentStatus:
        with self.lock:
            document = self.row(digest)
            row: sqlite3.Row | None = self.db.execute("SELECT * FROM jobs WHERE document=? AND kind='analysis' ORDER BY sequence DESC LIMIT 1", (digest,)).fetchone()
            job = job_adapter.validate_python(dict(row)) if row is not None else None
            state: JobState = job["state"] if job else "interrupted"
            if self.compatible(digest):
                state = "succeeded"
            elif state == "succeeded":
                state = "interrupted"
            result: DocumentStatus = {**document, "state": state, "stage": state, "completed": 0, "total": 0,
                      "error": error_adapter.validate_json(job["error"]) if job and job["error"] else None,
                      "retry_action": "POST analysis" if state in ("failed", "interrupted") else None}
            if job:
                progress = self.temp / f"{job['id']}.progress"
                if progress.exists():
                    try:
                        update = progress_adapter.validate_json(progress.read_text())
                        result["stage"] = update["stage"]
                        result["completed"] = update["completed"]
                        result["total"] = update["total"]
                    except (OSError, ValueError):
                        pass
            return result

    def delete(self, digest: str) -> None:
        """Remove persisted state after the owner has cancelled active work."""
        with self.lock:
            jobs = self.db.execute("SELECT id FROM jobs WHERE document=?", (digest,)).fetchall()
            for job in jobs:
                self.cleanup_job_files(str(job["id"]))
            directory = self.directory(digest)
            if directory.exists():
                shutil.rmtree(directory)
            self.db.execute("DELETE FROM jobs WHERE document=?", (digest,))
            self.db.execute("DELETE FROM documents WHERE id=?", (digest,))
            self.db.commit()

    def next_job(self) -> JobRecord | None:
        row: sqlite3.Row | None = self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY sequence LIMIT 1").fetchone()
        return job_adapter.validate_python(dict(row)) if row is not None else None

    def current_generation(self, job: JobRecord) -> bool:
        row = self.db.execute("SELECT generation FROM documents WHERE id=?", (job["document"],)).fetchone()
        return row is not None and row[0] == job["generation"]

    def update_job(self, job: JobRecord, state: JobState, error: JobError | None = None) -> None:
        self.db.execute("UPDATE jobs SET state=?,error=? WHERE id=? AND generation=?", (
            state, json.dumps(error) if error else None, job["id"], job["generation"]))
        self.db.commit()

    def publish(self, job: JobRecord, target: Path) -> None:
        destination = self.directory(job["document"]) / ("analysis.json" if job["kind"] == "analysis" else f"renders/{job['id']}.png")
        destination.parent.mkdir(exist_ok=True)
        target.replace(destination)
        self.evict()

    def cleanup_job_files(self, job_id: str) -> None:
        for artifact in self.temp.glob(f"{job_id}.*"):
            artifact.unlink(missing_ok=True)

    def evict(self) -> None:
        files = sorted(self.root.glob("*/renders/*.png"), key=lambda path: path.stat().st_mtime)
        total = sum(file.stat().st_size for file in files)
        for file in files:
            if total <= LIMITS["cache_bytes"]:
                break
            total -= file.stat().st_size
            file.unlink(missing_ok=True)
