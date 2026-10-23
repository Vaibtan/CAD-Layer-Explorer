# CAD Layer Explorer - Implementation Specification

Date: 2026-10-24

Status: Implementation authorized. Browser acceptance seam adopted by implementation request.

Delivery: Local application in Docker. This document is the implementation contract.

## Problem Statement

A person reviewing a CAD-exported structural PDF needs to discover the drawing's native layers, understand where each layer is used, assess how much content it contains, and see that content independently. A flattened page view cannot answer these questions. Layer names are author-defined, may be duplicated, and may describe the content inaccurately.

The live task requires an application that uploads a PDF, reports basic file and layer information, lists every native layer, identifies its pages and content amount, distinguishes empty layers, renders layers individually, and supports page navigation and layer toggling. The table and JSON must agree. Reprocessing the same bytes with the same supported analysis configuration must produce the same analytical results. The drawing and all derived content must remain on the user's machine. PDFs without layers, empty layers, and resource-intensive drawings must have explicit outcomes without crashing the application.

## Solution

Build a local, single-user web application with a plain HTML, CSS, and browser JavaScript interface, a FastAPI API, local PDF processing, SQLite operational state, and locally retained source files and derived artifacts. Use pypdf to inspect native PDF structure and PyMuPDF to render drawing content. The initial viewer displays backend-rendered images so full-page views, solo views, selected-layer views, and visibility measurements share one rendering engine.

The user uploads a document and sees processing progress. When analysis is available, the user can navigate pages, search and select layers, examine a table or the corresponding JSON, render a layer alone, combine visibility toggles, and download the analysis. The application preserves the PDF's original visibility configuration and provides explicit original, all-on, all-off, solo, and selected-layer views. Source files and reusable analysis remain local until the user deletes the document.

Explanations are deterministic descriptions of measured evidence: original names, referenced pages, source-operation counts, visibility results, and directly attributable text samples when available. Any inferred purpose is labeled and accompanied by its basis. No engineering interpretation is required, and a layer's name is never sufficient to establish its actual purpose.

### Shared vocabulary

| Term | Meaning |
| --- | --- |
| Document | The immutable uploaded PDF bytes, identified by SHA-256. |
| Layer / OCG | A native PDF optional content group. Its name is a label, not its identity. |
| Object reference | The PDF object number and generation identifying an OCG within a document. |
| Page-layer pair | One document page and one OCG referenced by that page's reachable content. |
| Referenced page | A page whose reachable content references an OCG, even if its marked section has no content-bearing operation. |
| Content page | A page containing at least one supported content-bearing operation attributed to an OCG. |
| Source-empty layer | A layer with no attributed supported content-bearing operations in a complete structural inspection. |
| No visible output | A render-profile-specific observation that differs from source emptiness. |
| Base content | Drawing content whose visibility is not controlled by an OCG. |
| OCMD | A PDF optional content membership dictionary expressing visibility through one or more OCGs. |
| Canonical manifest | The deterministic, versioned analytical data used by both the table and JSON. |
| Operational status | Processing progress, timings, retries, and runtime failures, kept outside the canonical manifest. |
| Strict solo | A view containing only the requested layer's drawing content, with unrelated layers and annotation overlays excluded. |

## User Stories

1. As a drawing reviewer, I want to upload a local PDF, so that I can inspect it without sending it to an external service.
2. As a drawing reviewer, I want to see the file size, PDF version, page count, encryption state, and layer availability, so that I understand what was accepted.
3. As a drawing reviewer, I want upload and processing progress, so that I can distinguish ongoing work from a stalled application.
4. As a drawing reviewer, I want actionable errors for invalid, encrypted, or unsupported documents, so that I know why processing cannot continue.
5. As a drawing reviewer, I want every native layer listed, so that unused and initially hidden groups are discoverable.
6. As a drawing reviewer, I want duplicate layer names kept separate, so that unrelated drawing content is not merged accidentally.
7. As a drawing reviewer, I want original layer names preserved exactly, so that I can compare the application with the source document.
8. As a drawing reviewer, I want to distinguish a layer's original visibility from my current selection, so that exploration does not change source facts.
9. As a drawing reviewer, I want to see the pages referencing each layer, so that I can find where it is used.
10. As a drawing reviewer, I want to distinguish references from content-bearing usage, so that an empty marked section does not imply drawing content.
11. As a drawing reviewer, I want layers filtered to the current page, so that the controls remain useful on a large drawing set.
12. As a drawing reviewer, I want to search and sort the layer table, so that I can locate groups quickly.
13. As a drawing reviewer, I want path, text-show, image-placement, and shading counts, so that content amount has a concrete definition.
14. As a drawing reviewer, I want per-page and document-wide measurements, so that I can understand a layer's distribution.
15. As a drawing reviewer, I want to identify source-empty layers, so that unused groups are distinguishable from useful drawing content.
16. As a drawing reviewer, I want invisible or clipped content distinguished from source emptiness, so that the application does not discard a populated layer incorrectly.
17. As a drawing reviewer, I want unsupported analysis marked as unknown or incomplete, so that missing measurements are not presented as zeros.
18. As a drawing reviewer, I want the original full-page view, so that I can orient myself before exploring layers.
19. As a drawing reviewer, I want to render one layer alone, so that I can inspect its actual drawing content.
20. As a drawing reviewer, I want to toggle multiple layers together, so that I can understand their relationship in the drawing.
21. As a drawing reviewer, I want original, all-on, and all-off controls, so that I can reset or compare visibility states easily.
22. As a drawing reviewer, I want page navigation, fit-to-page, zoom, and pan, so that I can examine both a sheet and its details.
23. As a drawing reviewer, I want a sharper bounded render when zooming, so that fine drawing details remain readable.
24. As a drawing reviewer, I want outdated render responses ignored, so that rapid toggles cannot replace my current view with an older selection.
25. As a drawing reviewer, I want base content disclosed when it remains visible, so that a combined view is not mislabeled as strict solo.
26. As a drawing reviewer, I want annotation notes reported separately, so that they do not inflate drawing-content counts or contaminate solo views.
27. As a drawing reviewer, I want evidence-based layer explanations, so that I can understand a group without trusting its name blindly.
28. As a drawing reviewer, I want directly attributable text samples when decoding is reliable, so that explanations have useful examples.
29. As a drawing reviewer, I want uncertain name-based interpretations labeled, so that I can distinguish observation from inference.
30. As a drawing reviewer, I want a readable table and corresponding JSON, so that visual inspection and programmatic consumption use the same facts.
31. As a drawing reviewer, I want to download the complete canonical analysis, so that I can inspect or reuse it locally.
32. As a drawing reviewer, I want repeat processing to produce the same completed analysis, so that results are reproducible.
33. As a drawing reviewer, I want previously analyzed documents available after reopening the app, so that I can resume work without repeating processing.
34. As a drawing reviewer, I want cached renders reused, so that revisiting a page or selection is efficient.
35. As a drawing reviewer, I want a document deletion action, so that I can remove its source, analysis, and derived artifacts from application-managed storage.
36. As a drawing reviewer, I want a valid PDF without native layers to remain viewable, so that the absence of layers is an understandable result.
37. As a drawing reviewer, I want unusually large or complex PDFs to complete within limits or fail clearly, so that they cannot take down the app.
38. As a drawing reviewer, I want interrupted work identified after restart, so that I can retry without trusting stale progress or incomplete results.
39. As a drawing reviewer, I want keyboard-accessible controls and visible loading and error states, so that the application remains usable during normal and failed operations.

## Implementation Decisions

### 1. Scope and current state

- Target one user on one machine. Hosted deployment, accounts, shared documents, and collaboration are deferred.
- Use FastAPI for the API and plain HTML, CSS, and browser JavaScript for the frontend (user amendment, 2026-10-24). Use uv for the backend environment and retain its dependency lock. No frontend framework or build tool is required.
- The current repository contains the supplied task, source drawing, an initialized Python 3.12 environment, and locked FastAPI, Uvicorn, and multipart dependencies. It has no application implementation, frontend, application tests, glossary, or ADRs. Exploratory PDF inspection and rendering are feasibility evidence only.
- Implementation pins pypdf 6.21.2 and PyMuPDF 1.26.7. PyMuPDF 2.0 loaded an unrelated ML layout model during import and stalled inside the 1 GiB worker limit; the leaner engine is used for the Docker acceptance run.
- PyMuPDF's AGPL/commercial licensing was explicitly accepted for this task. Reassess licensing before changing the distribution model or turning this into a proprietary product.
- Implement the complete specified behavior in vertical increments. An early milestone is not acceptance of the complete spec.

### 2. Module boundaries

| Module | Public responsibility |
| --- | --- |
| Web interface | Upload documents, display operational state and canonical analysis, manage page and visibility selection, request renders, and initiate deletion. |
| Document API | Validate requests and uploads, coordinate local persistence and jobs, expose analysis and rendering contracts, and return consistent errors. |
| PDF analysis | Discover OCGs and configurations, traverse content references, attribute source operations, produce counts and warnings, and build deterministic explanations. |
| PDF rendering | Apply an explicit visibility configuration to a fresh document instance, render with bounded settings, and report isolation capabilities and visibility observations. |
| Worker supervisor | Execute bounded child processes, enforce cancellation and resource limits, report progress, and prevent stale work from publishing results. |
| Local repository | Own immutable source bytes, canonical manifests, render artifacts, atomic publication, and deletion. |
| Operational store | Keep document records, upload metadata, job state, progress, and restart recovery in SQLite. |

Keep PDF libraries behind the analysis and rendering boundaries. The UI must not interpret raw PDF objects or independently recompute layer statistics. The analysis module returns structured domain results rather than HTTP responses.

### 3. Upload, identity, and storage lifecycle

- Stream uploads into application-managed temporary storage while hashing the complete byte sequence. Check actual bytes and parser acceptance rather than trusting extension or MIME type alone.
- Keep upload metadata, including the original filename and upload time, separate from canonical analytical facts.
- Identify a document by its SHA-256. Reuploading identical bytes reuses compatible analysis and artifacts; a different filename does not change layer identity or results.
- Serialize concurrent uploads of identical bytes into one stored document and one compatible analysis job. Never expose a partially written source or manifest.
- Source bytes are immutable. Visibility exploration and extraction must not rewrite the original PDF.
- Retain source documents and completed analyses until explicit deletion. Cache eviction may remove regenerable previews without deleting the source or manifest.
- Store documents and SQLite state under a local, git-ignored application data root. Choose application-controlled storage names, never user-provided paths.
- Delete removes the managed source, manifest, cached previews, temporary files, and operational records for that document. It does not delete the user's original file outside application storage.
- Before deletion completes, cancel or terminate in-flight work for that document. Use a document generation or cancellation token so late results cannot recreate deleted artifacts. A subsequent upload of the same bytes creates a new active generation.

### 4. Native layer discovery and attribution

- Treat an OCG as a distinct native layer even when its name duplicates another OCG's name. Its domain identity consists of the source hash, object number, and generation.
- Preserve original names, source configuration order, default visibility, and relevant configuration restrictions. Offer original-order display; use object-reference ordering for deterministic serialization.
- Discover all catalog OCGs, including unused groups, rather than relying only on a viewer's currently displayed layer panel.
- Resolve page content streams, inherited resources, marked-content scopes, and image or Form XObject optional-content associations. pypdf exposes parsed content-stream operations for this inspection.
- Traverse each Form placement with its effective resources and optional-content context. Repeated placements count repeatedly. Cache parsed structures where useful, but do not use a global visited set that undercounts repeated placements. Detect recursion cycles and enforce depth limits.
- Carry the complete optional-content condition through nested scopes. Handle unambiguous single-OCG attribution exactly. For content controlled jointly by multiple groups or an OCMD, preserve the controlling expression and report shared or conditional content separately; do not duplicate it into exclusive per-layer totals or claim exact attribution without support.
- Preserve known membership for unsupported constructs, and explicitly mark affected counts and emptiness as incomplete. Do not silently flatten conditional content into an arbitrary layer.
- A referenced page contains a reachable reference to a layer; a content page contains attributed supported source content. A resource dictionary entry alone does not establish active page usage.
- Base drawing content and annotations are separate categories, not fabricated native OCGs.

### 5. Content amount, emptiness, and explanations

- Define content amount as source-operation counts, not original CAD entity counts. Count a non-empty path-paint operation once, including a combined fill-and-stroke operation; do not count each line segment as a separate path.
- Count a text-show operation when it contains non-empty glyph data. Positioning-only text arrays do not add a content count. Such source content can be visually invisible because of text rendering mode or other graphics state.
- Count each image placement, including repeated and inline image placements, once. Report shading operations separately. State these definitions in the UI and JSON measurement metadata.
- Preserve separate category counts. If displaying a total, define it as their sum and label it source operations; it is not a physical-component estimate.
- Define source emptiness from complete structural inspection. A completely inspected group with zero content-bearing operations is empty. A referenced but empty marked section can therefore still be empty. Use an unknown value with an explicit status when inspection is incomplete.
- Maintain per-page and aggregate measurements. Aggregate totals are computed from the same per-page records exposed in JSON. Shared or conditional content is explicitly distinguished from exclusively attributed content.
- Measure visible output separately using a fixed RGB, white-background, annotation-disabled render profile at 36 DPI. Record the profile and pixel dimensions. Zero nonwhite pixels means no visible output at that profile, not proof that no content exists.
- The initial profile matches the exploratory 596 by 421 pixel render of the supplied rotated pages. It is a reproducible observation, not a universal high-resolution visibility guarantee.
- Generate explanations with versioned deterministic templates. Describe measured distribution and content categories first. Include text samples only when decoding and attribution are reliable; otherwise explain their absence.
- Any inferred purpose must say it is inferred and identify its basis. Preserve author spelling, including misspellings. Do not silently rename layers, hide apparent noise, or classify a group as dimensions, structure, or border solely from its name.
- Report SHX annotation counts and their availability separately. Default annotation overlays off in drawing previews and solo views. Preserve annotations in the source and disclose the preview policy.

### 6. Canonical manifest and reproducibility

| Record | Required information |
| --- | --- |
| Manifest identity | Schema version, analyzer version, source SHA-256, PDF engine versions, and normalized analysis settings. |
| Document facts | Byte size, PDF version, page count, layer availability, encryption information, and annotation summary. |
| Page facts | One-based page number, page label when present, media and crop boxes, rotation, displayed dimensions, and membership. |
| Layer facts | Stable ID, original name, object reference, source order, default visibility, referenced pages, content pages, category counts, emptiness and completeness, explanation, and warnings. |
| Page-layer facts | The same attributed counts, supported bounds when available, source-content status, render-profile visibility result, and attribution qualifications. |
| Capabilities | Supported rendering modes, strict-solo capability, base-content presence, and any deterministic analysis restrictions. |
| Conditional/base content | Separately identified measurements and supported conditions, without misrepresenting them as exclusive native layers. |

- The analysis cache key includes the document hash, schema and analyzer versions, engine versions, and normalized analysis settings. A changed engine, rule, or render profile creates a new analysis identity.
- Use stable ordering for layers, pages, category keys, samples, and warnings. Normalize bounded text samples consistently and use documented coordinate precision. The canonical serializer must be byte-stable for successfully completed analyses in the pinned environment.
- Do not put upload filenames, local paths, job IDs, timestamps, elapsed time, cache hits, or runtime error text inside canonical analytical results.
- Include deterministic unsupported-feature warnings in the manifest. Runtime timeouts, interruption, storage failures, and worker crashes belong to operational status.
- Publish a completed manifest atomically. Runtime-failed partial work may be displayed as explicitly provisional progress but must not replace a previously valid manifest or be exported as successful canonical analysis.
- The table, detail panel, JSON view, and JSON download all read the same manifest. Sorting and filtering are projections of that data. The default JSON download contains the complete manifest, and the UI makes its scope clear when the table is filtered.
- Current visibility selections are UI state and render inputs; toggling them does not alter canonical default visibility, counts, or explanations.

### 7. Rendering and interaction contract

- Render from an independently opened document in a child process. Do not share a live PyMuPDF document between threads or concurrent requests.
- Apply visibility by object identity with a complete explicit state, rather than toggling a reused mutable document or addressing groups by name. Verify that the selected configuration is active before rendering.
- Original mode uses the source's effective default view. All-on and all-off apply to native OCGs; base content is unaffected. Disclose source restrictions such as mutually exclusive radio groups. If honoring restrictions prevents a literal all-on state, explain the limitation rather than silently overriding it.
- Solo mode requests one OCG on and unrelated OCGs off. Strict solo is available only when the implementation can exclude unrelated content. Treat conditional memberships, unavoidable base content, and unsupported annotation cases as capability restrictions.
- For a file where base content remains visible, offer a clearly labeled selected-layer-with-base view or an explicit strict-solo-unavailable outcome. Never claim successful strict isolation merely because a layer was toggled.
- The supplied drawing must support strict solo across all 495 known page-layer pairs. Arbitrary PDFs may have narrower capabilities, which must be reported.
- Render selected combinations from the original page in original paint order. Do not reconstruct the result by stacking standalone layer images, because clipping, blending, and occlusion can change the result.
- Respect page rotation and crop boxes. Use a viewport mapping that remains consistent across fit, zoom, pan, and optional clipped-region rendering.
- Provide a fit render first and request a sharper bounded render for higher zoom. Pixel limits apply before allocation. Viewport rendering may be used to retain detail within the same pixel budget.
- Cache by source and generation, engine version, page, complete visibility state and mode, normalized viewport/scale, background and color profile, and annotation policy. Different visibility or render settings must not collide.
- Coalesce identical render requests, debounce rapid UI changes, and cancel queued obsolete work when possible. Tag responses with their requested selection. The UI displays only the response matching its current request and does not present an old image as the current state.
- Keep an uncached render path available to verification so successful cache reuse is not the only evidence of rendering correctness.

### 8. API contracts

Endpoint paths below are public HTTP contracts, not prescribed source-code locations.

| Endpoint | Contract |
| --- | --- |
| POST /api/documents | Accept a multipart PDF upload. Return document identity, job identity and current status; use 202 for queued processing and 200 for a reusable completed analysis. |
| GET /api/documents | List locally retained documents and operational summaries for reopening work. |
| GET /api/documents/{id}/status | Return the current state, stage, completed/total page progress, structured operational errors, and available retry actions. |
| POST /api/documents/{id}/analysis | Start or reuse analysis under the active profile, including explicit retry after an interrupted or failed attempt. |
| GET /api/documents/{id}/analysis | Return the completed canonical manifest with stable JSON and an analysis-identity ETag. Return a structured not-ready response while no valid manifest exists. Support JSON download through response disposition or an equivalent client download. |
| POST /api/documents/{id}/renders | Accept a one-based page number, rendering mode, OCG IDs where relevant, and a bounded normalized render profile. Return 200 with a ready artifact reference on a cache hit, or 202 with a render-job reference while queued. |
| GET /api/renders/{key} | Return the corresponding PNG when ready. For pending work return 202 with polling information; for failed or deleted work return a structured error. |
| DELETE /api/documents/{id} | Begin idempotent cancellation and removal. Return 202 while cleanup is pending and 204 when no managed document artifacts remain. |

- Reject foreign-document layer IDs, unknown layers, impossible page numbers, unsupported modes, and unbounded render requests with structured validation errors.
- Provide stable machine-readable error codes and readable messages for invalid PDFs, encryption rejection, oversized uploads, excessive page counts, unsupported constructs, queue saturation, resource limits, timeouts, unavailable analysis, and missing artifacts.
- Use 413 for oversized uploads, 422 for invalid input or unsupported requested capabilities, 429 for a full queue, 404 for missing resources, and 409 for a valid resource whose requested analysis is not ready. These cases must not leak stack traces or internal paths.
- Keep successful analytical payloads distinct from job envelopes. Retryable failures must identify the applicable retry action rather than implying success.

### 9. Work execution and resource limits

- Use one API process, one local supervisor, and at most one active PDF child process initially. A small local queue is sufficient; an external broker is unnecessary for this scope.
- Track queued, running, succeeded, failed, interrupted, and cancelled job states. Analysis is ready only after completed manifest publication. Deletion has a separate pending/completed lifecycle.
- Return progress while work runs. Keep the API responsive during parsing and rendering. Terminate and reap a timed-out child, then allow subsequent jobs to proceed in a fresh process.
- On startup, mark previously running jobs interrupted. Discard or quarantine incomplete temporary results and offer explicit retry. Previously completed analyses remain usable.
- Enforce resource budgets in the supervisor and parser. Checking compressed upload size alone does not protect against expansion or pathological content. If the parser cannot prevent an oversized intermediate allocation, enforce the child-process memory ceiling at the operating-system boundary on the supported Windows environment.
- Initial implementation defaults below are engineering choices made by this spec, not measured throughput or latency commitments. Expose them in local configuration and report active limits in relevant errors.

| Limit | Initial default |
| --- | --- |
| Upload size | 100 MiB |
| Pages per document | 200 |
| Active PDF children | 1 |
| Queued PDF jobs | 8, with identical requests coalesced |
| Render output | 4,000,000 pixels per request |
| Render child wall time | 15 seconds |
| Analysis job wall time | 300 seconds |
| PDF child memory | 1 GiB, enforced for the child and its descendants |
| Reachable Form/content nesting | 32 levels, with cycle detection |
| Decoded content budget | 32 MiB per stream and 256 MiB per document analysis |
| Render-cache size | 512 MiB, evicting regenerable least-recently-used artifacts |

- Queue limits and cache eviction must not delete original documents or completed manifests. Storage-full failures must preserve already valid documents and clean up failed uploads.
- The supplied drawing is required to complete under the defaults. Measure actual acceptance-machine behavior during implementation and adjust justified defaults explicitly if necessary.

### 10. Frontend and local-only behavior

- Present document information and progress first, then a page viewer, a searchable layer panel, a layer table, layer details, and a JSON view. Avoid loading all page previews or all standalone layer images at startup.
- Indicate current page, selected layer identities, render mode, loading state, active annotation policy, and isolation limitations. Distinguish unknown values from zero and unsupported behavior from an empty result.
- Preserve the user's current page and selection while changing table presentation. Reset controls restore a documented visibility mode. Selected layers absent from the current page have a clear no-content-on-this-page state.
- Provide explicit local-document reopening and deletion controls. A deletion confirmation may be part of the product because it removes retained user data; the implementation must still exercise deletion end to end.
- Keep controls keyboard accessible, label visibility switches, and announce status changes without relying solely on color.
- Serve production frontend assets from the same local origin as the API. During development, use a local proxy or an explicit loopback-only origin allowlist. Bind the server to loopback by default.
- Bundle dependencies, fonts, scripts, and UI assets locally. Drawing processing, previews, samples, diagnostics, and errors must not be sent to remote services. Do not execute embedded PDF JavaScript or automatically follow document links or attachments.
- Document how to install dependencies and launch both development and built modes on Windows. Runtime processing must work with outbound network access disabled after installation.

### 11. Delivery increments and completion gates

| Increment | Demonstrable result | Gate before moving on |
| --- | --- | --- |
| 1. End-to-end slice | Upload, basic document facts, native layer list, page view, and strict solo on the supplied drawing. | A browser workflow uses the real parser and renderer and distinguishes duplicate names. |
| 2. Analysis contract | Membership, category counts, emptiness, explanations, canonical table/JSON, and download. | Repeated analysis is deterministic; table/JSON agree; fixture-based counts and empty states are correct. |
| 3. Exploration and retention | Multi-layer toggles, original/all-on/all-off, zoom/pan, caching, document list, reopen, retry, and deletion. | Selection correctness, restart behavior, cache correctness, and removal are verified. |
| 4. Robustness and acceptance | Resource enforcement, local-only operation, unsupported-feature reporting, and complete edge-case coverage. | All acceptance scenarios below pass, with failures and limitations recorded explicitly. |

No increment is complete solely because internal unit tests pass or previews exist in a cache. Retain evidence at the user-visible and process boundaries named by each gate.

## Testing Decisions

### Test seam and prior art

**Adopted primary seam:** exercise the complete locally running app through the browser: upload, processing, analysis, table/JSON, page navigation, visibility selection, rendering, restart/reopen, and deletion. Use targeted HTTP/process-boundary checks for resource failures that are impractical to trigger reliably through browser interaction.

The implementation request authorizes this seam. Validate the running Docker application through the browser and targeted HTTP/process checks.

There is no existing application test suite or public module seam to reuse. Existing exploratory inspection and render probes establish feasibility for the supplied PDF, including its 495 page-layer pairs. They are prior evidence, not substitutes for acceptance tests of the application.

Use a browser automation runner capable of launching the local app and interacting with its UI. Include real PDF parsing and rendering in integration and acceptance coverage. Test external outcomes rather than private helper calls, source layout, SQL statements, library method-call sequences, or snapshots of incidental markup. Narrow pure-logic tests are justified only for PDF semantics that cannot be diagnosed adequately through a small fixture's public output.

### Acceptance scenarios

1. **Supplied drawing discovery:** upload the known 38-page source and obtain 38 distinct OCGs with 30 unique names and 495 referenced page-layer pairs. Each page uses between 6 and 20 groups. Source identity matches SHA-256 `33b334cc2c696c1fa1a03ddfca25838e6c2d483be006870a9aac94549ff17693`.
2. **Duplicate-name independence:** operate on the two distinct S - dim groups independently. The cover-page group isolates the logo and the structural-sheet group isolates dimension graphics. Neither the table nor rendering merges them.
3. **Full isolation coverage:** request actual uncached strict-solo renders for every supplied page-layer pair. At the fixed visibility profile, all 495 produce nonwhite output. Request all-off renders for all 38 pages and verify blank output. Also inspect representative full and isolated renders visually at a readable resolution.
4. **Viewer alignment:** rotated pages display landscape with the correct crop, and the same drawing coordinates remain aligned across full, solo, selected, and zoomed views. Validate representative geometry and labels, not merely image dimensions.
5. **Canonical equality:** analyze identical bytes through independent uncached runs under pinned versions and settings. The canonical JSON bytes match. Renaming an upload does not change analytical results. Operational job IDs and times may differ.
6. **Shared table and JSON data:** compare stable layer IDs, pages, counts, empty/unknown states, and explanations in the visible table/detail panel with downloaded JSON. Repeat after sorting, filtering, and toggling. Filtering does not silently change the full-export contract.
7. **Count semantics:** use small generated PDFs with known paths, combined fill/stroke, empty and non-empty text-show operations, images, repeated placements, inline images, and shadings. Verify exact public category counts and totals without treating them as CAD objects.
8. **Reference versus content:** include an unused OCG and an OCG referenced only by an empty marked section. Verify layer discovery, referenced pages, content pages, and source emptiness independently.
9. **Invisible content:** include clipped, off-page, white-on-white, transparent, and non-painting text content. Verify non-empty source evidence can coexist with no visible output at the recorded render profile.
10. **Initially hidden layers:** verify complete discovery and source counts do not omit hidden groups, original mode honors their initial state, and solo mode can reveal supported content without changing canonical facts.
11. **Nested and repeated content:** include repeated and nested Form placements, inherited resources, direct and named marked-content properties, and XObject-level optional content. Verify counts follow placements and effective context; cycles and excessive depth fail within limits.
12. **Conditional visibility:** include nested OCG conditions, OCMD expressions, and mutually exclusive configurations. Verify supported conditions correctly, or report explicit capability/attribution restrictions. Unknown attribution must not become zero counts or a false empty claim.
13. **Base content:** include drawing content outside all OCGs. Verify all-off can still display base content and that a selected-layer-with-base result is never labeled strict solo.
14. **Annotations:** confirm the supplied SHX notes are reported separately and overlays are disabled in default previews. Include visible and layer-associated annotation fixtures to verify limitations are disclosed without inflating drawing-source counts.
15. **No layers and scans:** accept a valid unlayered vector PDF and a scanned image PDF as viewable documents with no native layers. Return an empty layer list and a clear explanation; do not invent layers or require OCR.
16. **Render state and races:** request A, then B, then A through uncached and cached paths. Verify the exact selected groups each time. Deliberately delay responses and confirm the UI ignores stale results. Compare selected-combination renders with an independently rendered reference using the same engine and profile.
17. **Cache discrimination:** verify changes in page, visibility, scale/viewport, annotation policy, engine/profile identity, and document bytes cannot reuse an incompatible artifact. Verify eviction preserves source files and manifests.
18. **Reopen and restart:** stop and reopen the application after completed analysis and recover the document and results. Restart during active work and observe interrupted status and a functioning retry. Never expose unfinished output as a completed manifest.
19. **Deletion race:** delete while queued, running, and after completion. Confirm managed source, manifests, artifacts, temporary results, and operational records are gone, and late workers cannot recreate them. Repeated deletion is safe; reupload can succeed afterward.
20. **Validation:** exercise malformed or truncated PDFs, spoofed MIME types, encrypted PDFs, invalid page numbers, foreign or unknown OCG IDs, unavailable capabilities, and oversized render requests. Verify stable error codes and useful UI messages.
21. **Resource enforcement:** exercise upload and page caps, decoded-content expansion, child memory exhaustion, excessive nesting, queue saturation, and render/analysis timeouts. Verify bounded failure, child cleanup, API responsiveness, and a successful normal request afterward. These are process-boundary checks, not just raised exceptions inside the parser.
22. **Storage failure:** simulate inability to complete an upload or artifact write. Verify no partial manifest is published and already valid documents remain available.
23. **Local-only operation:** run the installed application with outbound networking blocked and exercise upload, analysis, viewing, toggling, export, reopen, and deletion. Observe browser and backend/child traffic; only permitted loopback communication is expected. Browser-only request interception is insufficient evidence for backend isolation.
24. **Usability:** verify keyboard operation, labels, visible progress, unavailable controls, errors, and current-selection indicators through the browser. Page and layer lists remain usable without eagerly rendering every combination.

### Evidence and completion reporting

- Record dependency versions, active limits, source hashes, commands, fixture identities, and outcomes for acceptance runs. Separate exploratory evidence, application verification, and unresolved limitations.
- For rendering, combine automated pixel/geometry assertions on controlled fixtures with visual inspection of representative drawing pages. Nonwhite pixels alone do not prove that the right layer rendered.
- Keep private PDF fixtures and generated artifacts local. Use synthetic fixtures for shareable edge cases; do not commit or publish the supplied drawing without separate authorization.
- A complete build passes all applicable acceptance scenarios under the declared limits. A timeout or unsupported input can be an expected bounded outcome for an adversarial fixture, but it is not successful analysis of the supplied drawing.

## Out of Scope

- Hosted deployment, remote storage, user accounts, authorization roles, collaboration, and multiple-user scheduling.
- External AI, cloud document APIs, embeddings, vector databases, semantic search, or external drawing uploads.
- Automatic structural engineering interpretation, quantity takeoff, compliance assessment, or guaranteed classification of walls, beams, dimensions, reinforcement, and other physical components.
- Recovering original CAD entity identities, DWG/DXF models, or layers that were flattened out of the PDF.
- OCR as a requirement for reading scanned documents or reconstructing missing layer structure.
- Editing the source drawing, removing apparent noise from it, renaming its layers, or modifying its saved visibility state.
- Exporting edited or layer-extracted PDF documents; the required export is canonical analysis JSON and previews support inspection.
- Browser-side PDF.js rendering in the first implementation. This remains a future option requiring identity mapping and rendering-parity evidence.
- Arbitrary-PDF feature completeness, unlimited resource usage, or universal exact attribution of unsupported optional-content expressions. Report capability limits explicitly.
- External worker brokers, distributed jobs, multi-server orchestration, and performance commitments beyond bounded local execution.
- Publishing the specification to a remote issue tracker or configuring one. The user selected local Markdown as the delivery destination.

## Further Notes

- The authoritative task is the supplied Live Task CAD Layer Explorer specification. This implementation spec incorporates the subsequent agreed local scope, evidence-based explanations, PDF-level counts, accepted PyMuPDF dependency, and retention-until-deletion policy. The user's request to create this spec adopts the proposed architecture as its basis.
- Source inspection found a 6,535,944-byte, unencrypted PDF 1.7 document with 38 pages. Each page has an 842 by 1191 point media/crop box and 270-degree rotation, producing a 1191 by 842 point landscape view.
- The source contains 38 OCG objects, all initially on, with a flat order and no detected alternate configurations, radio groups, locks, OCMDs, or Form XObjects. These properties simplify this fixture but are not safe assumptions for every upload.
- All 495 referenced page-layer pairs produced visible output in exploratory solo renders. All 38 all-off pages were white with annotation rendering both enabled and disabled at 36 DPI. No source-empty used group was found in this input, so synthetic empty-layer fixtures are necessary.
- The source has 3,009 Square annotations associated with AutoCAD SHX Text and no detected OCG membership. Their presence does not establish visible painted geometry. Annotation handling must remain a separate policy.
- The exploratory render pass took approximately nine seconds on the session machine. It is feasibility evidence, not an end-to-end latency target or product benchmark.
- Relevant primary documentation already consulted: [PyMuPDF optional content](https://pymupdf.readthedocs.io/en/latest/recipes-optional-content.html), [PyMuPDF document APIs](https://pymupdf.readthedocs.io/en/latest/document.html), [PyMuPDF process guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html), [PyMuPDF licensing](https://pymupdf.io/licensing), [pypdf generic objects and content streams](https://pypdf.readthedocs.io/en/stable/modules/generic.html), and [uv project environment guidance](https://docs.astral.sh/uv/guides/projects/). Revalidate API specifics during implementation if selecting different pinned versions.
- This spec intentionally names module responsibilities and public contracts without prescribing source-file organization. Implementation may choose a simple layout while preserving the behavior, domain identities, and acceptance boundaries defined here.
