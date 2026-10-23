# Implementation verification

Verified locally on 2026-10-24 against Docker Desktop's Linux engine 29.7.2. The app uses HTML, CSS, and browser JavaScript, as requested. No React, frontend package manager, CDN, remote document processing, or frontend build step is used.

## Reproduce the application

```powershell
docker compose up --build -d --wait
```

Open http://127.0.0.1:8000. The processor is isolated on an internal Docker network; nginx provides loopback-only ingress. SQLite, immutable uploads, manifests, and previews persist in the `cad-data` Docker volume. The Docker build excludes the supplied private PDF.

Dependencies are locked in `uv.lock`: Python 3.12 in the image, FastAPI 0.162.0, pypdf 6.21.2, PyMuPDF 1.26.7, NumPy 2.5.4, and psutil 7.2.2. PyMuPDF 2.0 was replaced because its automatic ML layout-model initialization stalled under the worker memory limit. The application does not need that model.

## Recorded results

| Boundary | Actual result |
| --- | --- |
| Docker build and startup | Image builds with the frozen lock; unprivileged API container becomes healthy; browser reaches loopback ingress. |
| Supplied drawing | SHA-256 `33b334cc2c696c1fa1a03ddfca25838e6c2d483be006870a9aac94549ff17693`; 6,535,944 bytes; PDF 1.7; unencrypted; 38 pages; 38 OCG identities; 30 unique names; 495 referenced page-layer pairs; 6–20 groups per page. |
| Isolation | Actual uncached HTTP render jobs for all 495 supplied page-layer pairs produced nonwhite pixels. All 38 uncached all-off pages were blank. The full HTTP run passed 13 tests in 568.65 seconds. |
| Independent image reference | Both distinct `S - dim` groups, selected combinations, original, all-on, and all-off matched independent original-document UI-state renders pixel for pixel. Visual inspection confirmed cover logo versus dimension graphics, landscape rotation, crop, geometry, and readable sheet labels. |
| Canonical repeatability | Two independent disposable workers in a container with `--network none` produced byte-identical final analyzer 1.3.0 JSON. SHA-256 of canonical bytes: `15c3eb629e61e0fc4639182f7b59abdaa79c371a0b07860df28d1ed3b4fcfeb8`. The two runs together took 134.24 seconds while other acceptance work was running. |
| Source semantics | Synthetic public-API checks passed exact path/text/image/shading counts; repeated and nested Forms; inline images; duplicate names; initially hidden, unused, and empty-scope groups; source content with invisible output; conditional attribution; base content; no-layer vector/scanned PDFs; annotations; rotated crops; and restricted configurations. |
| Browser | Actual upload, progress, selection, solo, original/all-off, fit/zoom, page navigation, search, sorting, table/JSON/download equality, local reopen, deletion confirmation, invalid PDF feedback, keyboard controls, and mobile width passed. Browser instrumentation recorded zero JavaScript errors and zero remote requests. Representative screenshots were visually reviewed. |
| Final image | 12 HTTP tests passed in 21.15 seconds; the previously completed full-sweep test was intentionally skipped in this short repeat. The complete browser workflow passed again. Final API canonical bytes matched the independent worker runs exactly, and ETag matched the manifest identity. |
| Render races | A deliberately held A response was released after B displayed and did not replace B. Selecting A again returned HTTP 200 from the server cache and displayed A. A separate mobile check waited for the fit render and verified image width stayed within the viewport. |
| Retention and restart | Completed manifest bytes survived restart. A specifically suspended active worker became interrupted after restart; incomplete output was unavailable; explicit retry succeeded. |
| Deletion | Deleting a specifically suspended worker removed source/manifest/render directory, operational jobs, and matching temporary artifacts. Repeated deletion and immediate reupload succeeded; stale work did not recreate the old generation. |
| Resource/process failures | Deliberately suspended workers hit shortened analysis/render deadlines and were reaped; subsequent normal work succeeded. A one-job queue returned structured 429 and recovered. Reduced upload/page/decoded-stream caps and 40 nested Forms failed clearly. A compact stream expanding toward 1 GiB hit the parser resource guard. A live PDF child's OS address-space soft/hard limits were both inspected as 1,073,741,824 bytes. |
| Storage/cache | Directory permission faults produced structured upload and artifact-publication failures without corrupting an existing manifest. Restoring permissions recovered normal work. Reduced cache capacity evicted previews while source and manifest stayed available. |
| Backend network isolation | External TCP connect returned Linux error 101 (`ENETUNREACH`); the processor had no external gateway. A 20-second packet capture during actual render processing observed only app/proxy Docker-local traffic and loopback. Browser request observation independently found no remote requests. |

The 533-render sweep used analyzer 1.2.0 before the final annotation-summary and API privacy polish. The renderer and PDF engine were unchanged. All supplied layer IDs, counts, and page details were compared with final analyzer 1.3.0 and were equal. Final 1.3.0 separately passed independent deterministic analyses, and the final image is checked again through the HTTP and browser workflows.

Operational progress, job IDs, filenames, timings, retries, cache hits, and errors stay outside canonical analysis. The ETag uses the analysis identity. API responses disable browser caching; clearing/deleting a drawing revokes its current preview blob. Server-side render caching remains available. Sources are not modified by exploration.

## Local evidence

Private artifacts remain under ignored `tmp/acceptance/`:

- `http-results.xml`: complete 13-test run including the 533 uncached renders.
- `final-http-results.xml`, `browser-evidence.json`: final image HTTP/browser checks.
- `drawing-cover.png`, `drawing-page-4.png`, `drawing-solo.png`, `mobile.png`: browser captures.
- `reference-evidence.json`, `reference-page-*-*.png`: independent image comparisons.
- `race-evidence.json`: deliberate stale-response, cached replay, and responsive-fit checks.
- `final-docker-analysis.json`, `determinism-evidence.json`: final canonical bytes and independent-run equality.
- `resource-evidence.json`, `restart-evidence.json`, `limits-evidence.json`, `backend-traffic.json`: fault, persistence, process-limit, and traffic observations.

The small diagnostic scripts used for the resource/reference/restart checks are retained beside those local artifacts. The reusable synthetic and browser acceptance runners live in `tests/`; run commands are in the root README.

## Explicit capability and evidence limits

- Source counts are PDF operations, not CAD objects or engineering quantities. Source bounds are unmeasured (`null`). Text samples are limited to directly attributed, reliably handled standard-font text; absence of a sample is stated explicitly.
- Joint/nested multi-group conditions and OCMDs are retained separately and make affected exclusive counts incomplete, with unknown emptiness. Base content, conditional content, restricted configurations, and unsupported pattern/Type 3/soft-mask internals prevent a strict-solo claim. The supplied drawing has none of those restrictions.
- Default previews exclude annotation overlays. The supplied file's 3,009 `AutoCAD SHX Text` annotations are reported separately; their text does not inflate source-operation counts.
- Visibility means nonwhite output at RGB/white/annotations-off/36 DPI. It is not proof of correct engineering meaning, and a blank render is not proof of source emptiness. Image-reference comparisons and visual review complement pixel-presence checks.
- Resource tests used deliberately lowered limits, suspended real workers, permission faults, and real parser expansion. They did not fill the host disk, force actual host-wide exhaustion, or exhaust every arbitrary PDF feature. The expansion fixture was stopped by the parser before it proved memory exhaustion. Linux OS-limit enforcement was inspected directly; native Windows development has monitoring rather than the Docker OS boundary.
- The input is local and single-user. Universal arbitrary-PDF correctness and every permutation in the spec's adversarial acceptance matrix are not claimed. Unsupported constructs return restrictions or bounded failures rather than fabricated exact analysis.

Primary API references used during implementation: [PyMuPDF optional content](https://pymupdf.readthedocs.io/en/latest/recipes-optional-content.html), [document visibility controls](https://pymupdf.readthedocs.io/en/latest/document.html), [low-level dictionary access](https://pymupdf.readthedocs.io/en/latest/recipes-low-level-interfaces.html), [pypdf content streams](https://pypdf.readthedocs.io/en/stable/modules/generic.html), and [pypdf processing limits](https://pypdf.readthedocs.io/en/stable/modules/configuration.html). Application behavior was checked with the pinned versions rather than inferred solely from documentation.

## Architecture and typing review - 2026-10-24

The architecture review examined the backend, browser code, specification, tests, and Docker configuration. The original application implementation was untracked in Git, so the deployed image's source was also copied to ignored review storage for comparison. Earlier results above are historical evidence; this section records the subsequent changes and their fresh checks.

### Findings and corrections

| Priority | Reproduced finding | Correction and regression seam |
| --- | --- | --- |
| P1 | An empty or malformed child error file raised during decoding, terminated the sole supervisor thread, and left work permanently running. | Validate diagnostic records and fall back to a structured worker failure. Four real-child regressions prove subsequent work still succeeds through `DocumentWork`. |
| P2 | A Form lost its inherited font selection, allowing Type 3 glyph content to be labeled complete and eligible for strict solo. | The content inspector carries the resolved font object through Form calls, graphics-state save/restore, and ExtGState font selection. Real-PDF regressions cover local, inherited, ExtGState, and same-name resource-collision cases. |
| P2 | Restricted configurations advertised rendering modes that the request handler rejected. | Derive advertised modes from actual visibility capabilities. A restricted document advertises only original mode. |
| P2 | Opening a second drawing left the first drawing's layer evidence visible. | Reset document-owned details when changing or clearing the drawing; browser regression switches between two distinct evidence sets. |
| P2 | Deleting a failed drawing left its retry control active without a selected document. | Reset retry visibility when clearing document state; browser regression deletes a failed drawing. |
| P2 | A failed request from an earlier document opening could replace the active drawing's status notice. | Check document/version ownership for rejected opening requests as well as successful responses; browser regression delays the old failure until the new drawing is ready. |

### Implemented module ownership

- `DocumentWork` owns complete upload, analysis, preview, retry, and deletion operations. Its HTTP callers no longer coordinate SQL, locks, filesystem paths, cache identities, or child-process rules.
- `JobSupervisor` owns execution, active-child cancellation, process reaping, timeout/memory monitoring, and per-job failure recovery. It is composed with storage, without a generic repository hierarchy.
- `Repository` owns SQLite and filesystem persistence, generation-aware job state, manifest compatibility, and atomic artifact publication. It does not launch processes or own an execution thread.
- `PdfAnalyzer`, its private content inspector, and `PdfRenderer` concentrate analysis orchestration, effective source context, and native visibility/rendering rules respectively.
- Shared typed records describe canonical manifests, conditional expressions, worker messages, progress, errors, requests, and database rows. Pydantic adapters validate JSON and SQLite records at their seams. A narrow protocol declaration contains PyMuPDF's untyped interface; application code does not use catch-all `Any` annotations or type-ignore directives.
- The plain JavaScript implementation is retained. Only the three reproduced browser defects were changed; the separate broader browser-exploration refactor was not selected.

Analyzer 1.4.0 invalidates old analytical caches after the inherited-font and capability corrections. Before increasing the version, the refactored analyzer reproduced the supplied drawing's original canonical bytes exactly. The source PDF remains immutable and retained earlier documents can be reanalyzed.

### Fresh checks completed during the review

- Strict mypy passes all ten production Python modules for both the Windows host and Linux target. Every production function has argument and return annotations.
- Thirteen maintained backend regressions pass using temporary storage, generated PDFs, and real child processes. They include malformed diagnostic recovery, effective font context, supported modes, invalid worker-message shapes, and deterministic active-child deletion followed by same-byte reupload into a fresh generation and successful analysis/preview.
- Three isolated browser regressions pass. They use controlled responses to reproduce browser ownership and stale-failure conditions and are not presented as PDF/backend acceptance.
- Independent final source review found no new concrete defect in the composition refactor. A separate temporary-storage experiment exercised active cancellation, immediate reupload, analysis, preview, and cleanup.
- The visual architecture report was inspected at 1440 and 390 pixels: before/after diagrams render, headings and content do not overlap, and the page has no horizontal overflow or browser-script errors.

The final application checks run in a separate Docker Compose project on loopback port 8001 with its own data volume. The pre-existing application on port 8000 and its retained documents are preserved. Review artifacts are under ignored `tmp/review`; the candidate HTML report is in the OS temporary directory, as required by the architecture skill.

### Final image results

| Check | Fresh result |
| --- | --- |
| Strict typing | `uv run mypy` and `uv run mypy --platform linux` pass all ten production modules. The dependency lock check also passes. |
| HTTP acceptance | All thirteen HTTP cases passed, including 495 uncached solo renders and 38 uncached all-off renders. The combined HTTP/backend invocation passed 25 cases in 419.99 seconds. |
| Backend regressions | All thirteen review regressions passed in a separate final run. Twelve also ran in the combined invocation; the deterministic active-deletion/new-generation case was added and verified afterward. There are 26 unique passing HTTP/backend cases across the recorded reports. |
| Full browser workflow | The final Docker image passes upload, processing, page navigation, visibility controls, zoom/fit, table/JSON/download agreement, reopen, deletion, invalid-PDF feedback, keyboard controls, and mobile rendering. Instrumentation recorded zero JavaScript errors and zero remote requests. |
| Screenshot verification | The runner now waits for completed image decoding and uses viewport screenshots; full-page capture had triggered resize/rendering during capture. Desktop original/solo and mobile screenshots were visually inspected with the drawing actually displayed. |
| Browser regressions | All three isolated ownership/race checks passed again; current-document failures still display while stale failures are ignored. |
| Independent determinism | Two fresh disposable worker processes in a network-disabled container produced byte-identical analyzer 1.4.0 JSON, also matching the actual HTTP response and ETag. The source still has 38 pages, 38 OCGs, and 495 page-layer pairs. |

Final canonical JSON has 171,075 bytes. Its SHA-256 is `39ccd9491654afba3925fbce8452460954a4ef99c4328f4f09f3795db84735ad`; its analysis identity and HTTP ETag are `344578ee6580965ddca09ae326f2fdb78714c2f4e3948970d2d759f43dd0ed98`.

Fresh evidence is recorded in `tmp/review/final-http-and-backend.xml`, `tmp/review/final-backend.xml`, `tmp/review/determinism-evidence.json`, `tmp/review/final-http-manifest.json`, and the browser evidence/screenshots under `tmp/review/browser`. These contain local/private artifacts and remain ignored by Git.

The earlier lowered-limit, permission-fault, OS-limit-inspection, and packet-capture matrix was not replayed in full during this review. Fresh checks specifically cover the changed typing, interpretation, document-work, execution, and browser-ownership seams; the earlier capability limits remain applicable.

Typing references checked for this pass: [mypy configuration](https://github.com/python/mypy/blob/master/docs/source/config_file.rst), [Pydantic 2.14.1 TypedDict validation](https://github.com/pydantic/pydantic/blob/v2.14.1/docs/api/standard_library_types.md), and [Pydantic named recursive types](https://github.com/pydantic/pydantic/blob/v2.14.1/docs/concepts/types.md). Runtime behavior was verified with the locked dependencies.
