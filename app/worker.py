"""Disposable PDF process; only the supervisor publishes its output."""
import json
import os
import sys
from pathlib import Path

from .settings import LIMITS


def main() -> None:
    target = Path(sys.argv[2])
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (LIMITS["memory_bytes"], LIMITS["memory_bytes"]))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from .models import worker_job_adapter
    from .pdf import PdfError, analyze, canonical, pixmap
    import pypdf
    from pypdf.errors import LimitReachedError

    def progress(stage: str, done: int, total: int) -> None:
        temp = target.with_suffix(".progress.tmp")
        temp.write_text(json.dumps({"stage": stage, "completed": done, "total": total}))
        temp.replace(target.with_suffix(".progress"))

    try:
        payload = worker_job_adapter.validate_json(Path(sys.argv[1]).read_bytes())
        if payload["kind"] == "analysis":
            pypdf.overwrite_configuration(
                zlib_maximum_output_length=LIMITS["stream_bytes"],
                array_based_stream_maximum_output_length=LIMITS["stream_bytes"],
                lzw_maximum_output_length=LIMITS["stream_bytes"],
                run_length_maximum_output_length=LIMITS["stream_bytes"],
                stream_decoding_work_maximum_length=LIMITS["decoded_bytes"],
            )
            target.write_bytes(canonical(analyze(payload["source"], payload["document"], progress)))
        else:
            p = payload["request"]
            pix = pixmap(payload["source"], p["page"], p["mode"], p["xrefs"], p["scale"], p["annotations"])
            target.write_bytes(pix.tobytes("png"))
    except PdfError as exc:
        target.with_suffix(".error").write_text(json.dumps({"code": exc.code, "message": exc.message}))
        sys.exit(2)
    except MemoryError:
        target.with_suffix(".error").write_text(json.dumps({"code": "memory_limit", "message": "PDF processing exceeded the child memory limit."}))
        sys.exit(2)
    except LimitReachedError:
        target.with_suffix(".error").write_text(json.dumps({"code": "resource_limit", "message": "PDF parsing exceeded a configured decompression, structure, or parsing-work limit. Use a less complex PDF."}))
        sys.exit(2)
    except Exception:
        target.with_suffix(".error").write_text(json.dumps({"code": "invalid_pdf", "message": "PDF processing failed. The PDF may be malformed or use unsupported content."}))
        sys.exit(2)


if __name__ == "__main__":
    main()
