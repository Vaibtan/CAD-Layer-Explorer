# CAD Layer Exploration

The language of inspecting native PDF drawing layers and retaining their local evidence.

## Language

**Document**:
The immutable bytes of one uploaded PDF drawing, identified independently of its filename.
_Avoid_: Drawing session

**Document generation**:
One retained lifetime of a document, beginning with acceptance and ending with deletion. Uploading the same bytes after deletion starts a new generation.
_Avoid_: PDF revision

**Document work**:
The inspection or preview-generation work belonging to a retained document generation. Results from an earlier generation cannot become evidence for a later one.

**Layer**:
A native PDF optional content group with its own object identity; its author-defined name is a label and may duplicate another layer's name.
_Avoid_: CAD entity, inferred component

**Page-layer pair**:
A page and a native layer referenced by that page's reachable content.

**Source operations**:
The counted path paints, non-empty text shows, image placements, and shadings in the exported PDF.
_Avoid_: CAD objects, physical quantities

**Source emptiness**:
The absence of attributed source operations after complete inspection. Incomplete attribution leaves source emptiness unknown.
_Avoid_: Blank preview

**Visible output**:
The nonwhite pixels observed under a declared rendering profile. This observation is separate from source emptiness and engineering meaning.

**Base content**:
Drawing content whose visibility is not controlled by a native layer.
_Avoid_: Synthetic layer

**Strict solo**:
A preview containing one selected layer's drawing content with unrelated layers and annotation overlays excluded.
_Avoid_: Selected layer with base content

**Canonical manifest**:
The completed, reproducible analytical facts for a document under a declared analysis profile. The evidence table and JSON export present the same manifest.
_Avoid_: Job status, session state
