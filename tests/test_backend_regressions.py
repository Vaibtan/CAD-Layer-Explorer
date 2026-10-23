"""Review regressions through real PDF and disposable-work interfaces.

These tests use isolated temporary storage, never the retained Docker volume.
"""
import hashlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject, NumberObject

from app.models import RenderRequest, worker_job_adapter
from app.pdf import analyze, pixmap, visible
from app.document_work import DocumentWork, PreviewReady
from app.repository import StoreError
from fixtures import dictionary, fixture, stream


def type3_form(path: Path, font_source: str) -> Path:
    """The same Type 3 glyph selected locally, inherited, or through ExtGState."""
    original = fixture(path)
    writer = PdfWriter(clone_from=PdfReader(original))
    page = writer.pages[0]
    resources = page["/Resources"]
    glyph = stream(writer, b"1000 0 0 0 1000 1000 d1 0 0 1000 1000 re f")
    font = writer._add_object(dictionary(
        Type=NameObject("/Font"), Subtype=NameObject("/Type3"),
        FontBBox=ArrayObject([NumberObject(n) for n in [0, 0, 1000, 1000]]),
        FontMatrix=ArrayObject([FloatObject(0.001), NumberObject(0), NumberObject(0),
                                FloatObject(0.001), NumberObject(0), NumberObject(0)]),
        CharProcs=dictionary(A=glyph),
        Encoding=dictionary(Type=NameObject("/Encoding"),
                            Differences=ArrayObject([NumberObject(65), NameObject("/A")])),
        FirstChar=NumberObject(65), LastChar=NumberObject(65),
        Widths=ArrayObject([NumberObject(1000)]), Resources=dictionary(),
    ))
    resources["/Font"][NameObject("/F3")] = font
    form_text = b"BT /F3 40 Tf 20 20 Td (A) Tj ET" if font_source == "form" else b"BT 20 20 Td (A) Tj ET"
    form_resources = {}
    if font_source == "resource_collision":
        # Parent /F3 is Type 3; the Form's identically named resource is Type 1.
        # Inherited font selection retains the actual parent's font object.
        form_resources = {"Resources": dictionary(Font=dictionary(F3=resources["/Font"]["/F1"]))}
    form = stream(writer, form_text, Type=NameObject("/XObject"), Subtype=NameObject("/Form"),
                  BBox=ArrayObject([NumberObject(n) for n in [0, 0, 240, 160]]), **form_resources)
    resources["/XObject"][NameObject("/Inherited")] = form
    if font_source == "extgstate":
        resources[NameObject("/ExtGState")] = dictionary(
            GS=writer._add_object(dictionary(Font=ArrayObject([font, NumberObject(40)]))))
        selection = b"/GS gs"
    else:
        selection = b"BT /F3 40 Tf ET"
    page[NameObject("/Contents")] = stream(writer, b"/OC /A BDC " + selection + b" /Inherited Do EMC")
    with path.open("wb") as output:
        writer.write(output)
    return path


@pytest.mark.parametrize("font_source", ["form", "parent", "extgstate", "resource_collision"])
def test_type3_font_context_never_claims_complete_solo(tmp_path, font_source):
    path = type3_form(tmp_path / f"{font_source}.pdf", font_source)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = analyze(path, digest)
    assert visible(pixmap(path, 1, "original", [], 1))["nonwhite_pixels"] > 0
    assert result["layers"][0]["counts"]["text_shows"] == 1
    assert not result["layers"][0]["complete"]
    assert not result["capabilities"]["strict_solo"]
    assert any("Type 3" in warning for warning in result["warnings"])


def test_restricted_modes_advertise_only_supported_requests(tmp_path):
    path = fixture(tmp_path / "restricted.pdf", "restricted")
    result = analyze(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert not result["capabilities"]["custom_visibility"]
    assert result["capabilities"]["modes"] == ["original"]


def wait_terminal(repo, digest):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = repo.status(digest)
        if status["state"] in ("failed", "succeeded", "interrupted"):
            return status
        time.sleep(0.05)
    pytest.fail("Isolated work did not reach a terminal state")


@pytest.mark.parametrize("error_bytes", [b"", b"{", b"[]", b'{"code":true,"message":[]}'])
def test_bad_worker_error_does_not_kill_queue(tmp_path, monkeypatch, error_bytes):
    real_popen = subprocess.Popen
    launched = 0

    def launch(command, **kwargs):
        nonlocal launched
        launched += 1
        if launched == 1:
            script = (
                "from pathlib import Path; import sys; "
                f"Path(sys.argv[1]).with_suffix('.error').write_bytes({error_bytes!r}); "
                "sys.exit(2)"
            )
            return real_popen([sys.executable, "-c", script, command[-1]], **kwargs)
        return real_popen(command, **kwargs)

    monkeypatch.setattr("app.jobs.subprocess.Popen", launch)
    work = DocumentWork(tmp_path / "isolated-data")
    try:
        broken = tmp_path / "failed-upload.pdf"
        broken.write_bytes(b"%PDF-1.7\nfailed-child")
        digest = hashlib.sha256(broken.read_bytes()).hexdigest()
        with broken.open("rb") as source:
            work.upload(source, "failed.pdf")
        failed = wait_terminal(work, digest)
        assert failed["state"] == "failed"
        assert failed["error"]["code"] == "worker_failed"

        valid = fixture(tmp_path / "recovery.pdf", "plain")
        recovery = hashlib.sha256(valid.read_bytes()).hexdigest()
        with valid.open("rb") as source:
            work.upload(source, "recovery.pdf")
        assert wait_terminal(work, recovery)["state"] == "succeeded"
        assert json.loads(work.read_analysis(recovery).data)["document"]["page_count"] == 1
        assert launched == 2
    finally:
        work.close()


@pytest.mark.parametrize("payload", [
    b'{"document":"d","kind":"render","source":"p.pdf","request":null}',
    b'{"document":"d","kind":"analysis","source":"p.pdf","request":{"page":1}}',
    b'{"document":"d","kind":"unknown","source":"p.pdf","request":null}',
])
def test_worker_protocol_rejects_incompatible_job_shapes(payload):
    with pytest.raises(ValidationError):
        worker_job_adapter.validate_json(payload)


def test_active_deletion_and_reupload_keep_generations_separate(tmp_path, monkeypatch):
    """Hold a real first child so deletion cannot pass only by winning a race."""
    data = fixture(tmp_path / "generation.pdf", "plain").read_bytes()
    started = tmp_path / "child-started"
    real_popen = subprocess.Popen
    launched = 0

    def launch(command, **kwargs):
        nonlocal launched
        launched += 1
        if launched == 1:
            script = "from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text('started'); time.sleep(60)"
            return real_popen([sys.executable, "-c", script, str(started)], **kwargs)
        return real_popen(command, **kwargs)

    monkeypatch.setattr("app.jobs.subprocess.Popen", launch)
    work = DocumentWork(tmp_path / "isolated-generations")
    try:
        digest = work.upload(io.BytesIO(data), "first.pdf")["id"]
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists(), "The first child must actually be running before deletion"
        original_generation = work.status(digest)["generation"]
        work.delete(digest)
        with pytest.raises(StoreError) as deleted:
            work.status(digest)
        assert deleted.value.status == 404

        assert work.upload(io.BytesIO(data), "second.pdf")["id"] == digest
        current = work.status(digest)
        assert current["generation"] != original_generation
        assert current["filename"] == "second.pdf"
        assert wait_terminal(work, digest)["state"] == "succeeded"
        receipt = work.request_render(digest, RenderRequest(page=1, mode="original", scale=0.5))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = work.read_preview(receipt["key"])
            if isinstance(result, PreviewReady):
                assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
                break
            time.sleep(0.05)
        else:
            pytest.fail("A new-generation preview did not complete after active deletion")
        work.delete(digest)
        assert work.list_documents() == []
        with pytest.raises(StoreError) as preview_deleted:
            work.read_preview(receipt["key"])
        assert preview_deleted.value.status == 404
    finally:
        work.close()
