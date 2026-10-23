"""The document-work interface shared by HTTP handlers and acceptance tests.

Own upload, analysis, preview, retry and deletion as complete use cases. Storage
and execution are composed here, so callers never coordinate their locks, paths,
queue records, child processes, cache identity or document generations.
"""
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .jobs import JobSupervisor
from .models import (
    AnalysisQueued, AnalysisReady, DocumentStatus, JobError, JobState,
    NormalizedRender, RenderRequest, RenderResult, UploadResult, error_adapter,
)
from .repository import Repository, StoreError
from .settings import DATA, LIMITS


@dataclass(frozen=True)
class AnalysisArtifact:
    data: bytes
    identity: str


@dataclass(frozen=True)
class PreviewReady:
    data: bytes


@dataclass(frozen=True)
class PreviewPending:
    state: JobState
    url: str


@dataclass(frozen=True)
class PreviewFailed:
    error: JobError


class DocumentWork:
    def __init__(self, root: str | Path = DATA) -> None:
        self._repository = Repository(root)
        self._jobs = JobSupervisor(self._repository)

    def close(self) -> None:
        self._jobs.close()
        self._repository.close()

    def upload(self, stream: BinaryIO, filename: str) -> UploadResult:
        """Retain a streamed upload and reuse or queue its immutable analysis.

        The caller retains ownership of the input stream.
        """
        repository = self._repository
        temp = repository.temp / f"upload-{uuid.uuid4().hex}"
        size = 0
        digest = hashlib.sha256()
        try:
            with temp.open("wb") as output:
                while chunk := stream.read(1024**2):
                    size += len(chunk)
                    if size > LIMITS["upload_bytes"]:
                        raise StoreError(413, "upload_limit", f"Upload exceeds {LIMITS['upload_bytes']} bytes.")
                    digest.update(chunk)
                    output.write(chunk)
            with temp.open("rb") as source:
                if not source.read(1024).lstrip().startswith(b"%PDF-"):
                    raise StoreError(422, "invalid_pdf", "Upload a valid PDF file.")
            document_id = digest.hexdigest()
            with repository.lock:
                repository.retain(temp, document_id, filename, size)
                if repository.compatible(document_id):
                    return {"id": document_id, "state": "succeeded", "job_id": None}
                job_id = self._jobs.enqueue(document_id, "analysis")
                return {"id": document_id, "state": "queued", "job_id": job_id}
        except OSError as error:
            raise StoreError(507, "storage_failure", "Could not retain upload. Free local disk space and retry.") from error
        finally:
            temp.unlink(missing_ok=True)

    def list_documents(self) -> list[DocumentStatus]:
        return self._repository.list_documents()

    def status(self, digest: str) -> DocumentStatus:
        return self._repository.status(digest)

    def retry_analysis(self, digest: str) -> AnalysisReady | AnalysisQueued:
        repository = self._repository
        with repository.lock:
            repository.row(digest)
            if repository.compatible(digest):
                return {"id": digest, "state": "succeeded"}
            return {"job_id": self._jobs.enqueue(digest, "analysis"), "state": "queued"}

    def read_analysis(self, digest: str) -> AnalysisArtifact:
        repository = self._repository
        with repository.lock:
            data = repository.manifest(digest).read_bytes()
            identity = repository.read_manifest(digest)["analysis_identity"]
            return AnalysisArtifact(data, identity)

    def request_render(self, digest: str, request: RenderRequest) -> RenderResult:
        repository = self._repository
        with repository.lock:
            manifest = repository.read_manifest(digest)
            if request.page > len(manifest["pages"]):
                raise StoreError(422, "invalid_page", "Page does not exist.")
            known = {layer["id"]: layer["object_reference"]["number"] for layer in manifest["layers"]}
            if any(layer not in known for layer in request.layers):
                raise StoreError(422, "invalid_layer", "A layer is unknown or belongs to another document.")
            if request.mode == "solo" and (len(set(request.layers)) != 1 or not manifest["capabilities"]["strict_solo"] or request.annotations):
                raise StoreError(422, "strict_solo_unavailable", "Strict solo requires one layer, annotations off, and no base/conditional content or configuration restrictions. Use selected layers with base instead.")
            if request.mode != "original" and not manifest["capabilities"]["custom_visibility"]:
                raise StoreError(422, "visibility_restricted", "Custom visibility is unavailable for restricted PDF configurations.")
            page = manifest["pages"][request.page - 1]
            if math.ceil(page["width"] * request.scale) * math.ceil(page["height"] * request.scale) > LIMITS["pixels"]:
                raise StoreError(422, "render_limit", f"Render exceeds {LIMITS['pixels']} pixels. Reduce zoom.")
            normalized: NormalizedRender = {
                "page": request.page, "mode": request.mode,
                "xrefs": sorted({known[layer] for layer in request.layers}) if request.mode in ("solo", "selected") else [],
                "scale": request.scale, "annotations": request.annotations}
            identity = {"document": digest, "generation": repository.row(digest)["generation"],
                        "analysis": manifest["analysis_identity"], "request": normalized,
                        "nonce": uuid.uuid4().hex if request.uncached else None}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            path = repository.directory(digest) / "renders" / f"{key}.png"
            if path.exists():
                path.touch()
                return {"key": key, "url": f"/api/renders/{key}", "state": "succeeded", "request": normalized}
            self._jobs.enqueue(digest, "render", normalized, key)
            return {"key": key, "url": f"/api/renders/{key}", "state": "queued", "request": normalized}

    def read_preview(self, key: str) -> PreviewReady | PreviewPending | PreviewFailed:
        repository = self._repository
        with repository.lock:
            job = repository.render_job(key)
            if not job:
                raise StoreError(404, "render_missing", "Render was not found.")
            if job["state"] in ("failed", "interrupted"):
                error: JobError = error_adapter.validate_json(job["error"]) if job["error"] else {
                    "code": "worker_failed", "message": "PDF work did not complete. Retry the render."}
                return PreviewFailed(error)
            path = repository.directory(job["document"]) / "renders" / f"{key}.png"
            if path.exists():
                path.touch()
                return PreviewReady(path.read_bytes())
            if job["state"] == "succeeded":
                raise StoreError(404, "render_evicted", "Preview was evicted. Request the render again.")
            return PreviewPending(job["state"], f"/api/renders/{key}")

    def delete(self, digest: str) -> None:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise StoreError(404, "document_missing", "Document was not found.")
        with self._repository.lock:
            self._jobs.cancel_document(digest)
            self._repository.delete(digest)
