"""PDF inspection and rendering. No live document objects escape analysis."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeAlias, cast

import numpy as np
import pypdf
from pypdf import PdfReader
from pypdf.generic import ContentStream, IndirectObject

from .models import (
    AnalysisBody, AnalysisManifest, AnalysisProfile, BaseContent, Category,
    ConditionalContent, ConditionalExpression, ConditionalOperation, ContentCounts, Layer, ManifestCondition,
    ObjectReference, PageFacts, ProgressCallback, RenderMode, SourceCondition, VisibleOutput,
)
from .pdf_engine import Document, Pixmap, engine as fitz
from .settings import LIMITS

ANALYZER = "1.4.0"
CATEGORIES: tuple[Category, ...] = ("paths", "text_shows", "images", "shadings")
PdfDictionary: TypeAlias = Mapping[str, object]
Operation: TypeAlias = tuple[Sequence[object], bytes]


class PdfError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def counts() -> ContentCounts:
    return {"paths": 0, "text_shows": 0, "images": 0, "shadings": 0}


def operation_total(value: ContentCounts) -> int:
    return sum(value[category] for category in CATEGORIES)


def profile() -> AnalysisProfile:
    return {"schema_version": "1", "analyzer_version": ANALYZER,
            "engines": {"pypdf": pypdf.__version__, "pymupdf": fitz.VersionBind},
            "settings": {"visibility_dpi": 36, "background": "white", "colorspace": "RGB", "annotations": False,
                         "depth": LIMITS["depth"], "stream_bytes": LIMITS["stream_bytes"], "decoded_bytes": LIMITS["decoded_bytes"]}}


def ref(value: object) -> ObjectReference | None:
    if not isinstance(value, IndirectObject):
        value = getattr(value, "indirect_reference", None)
    return (value.idnum, value.generation) if isinstance(value, IndirectObject) else None


def resolve(value: object) -> object:
    # Every pypdf object is self-resolving, but indirect references are the only
    # values whose resolution changes the underlying object.
    return value.get_object() if isinstance(value, IndirectObject) else value


def dictionary(value: object) -> PdfDictionary:
    value = resolve(value)
    if isinstance(value, dict):
        return cast(Mapping[str, object], value)
    return {}


def array(value: object) -> Sequence[object]:
    value = resolve(value)
    if isinstance(value, (list, tuple)):
        return cast(Sequence[object], value)
    return ()


class PdfRenderer:
    """Own native visibility configuration and the render pixel budget."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def open_view(self, mode: RenderMode = "original", selected: Sequence[int] = ()) -> Document:
        doc = fitz.open(self.path)
        try:
            if mode != "original" and doc.get_ocgs():
                all_refs = sorted(doc.get_ocgs())
                on = all_refs if mode == "all-on" else sorted(selected)
                if mode == "all-off":
                    on = []
                # Persist an identity-ordered configuration in a disposable copy.
                # UI ordinals, never duplicate names, activate the requested state.
                obj = doc.pdf_catalog()
                key_path: list[str] = []
                for key in ("OCProperties", "D"):
                    key_path.append(key)
                    kind, value = doc.xref_get_key(obj, "/".join(key_path))
                    if kind == "xref":
                        obj = int(value.split()[0])
                        key_path = []
                kind, raw = doc.xref_get_key(doc.pdf_catalog(), "OCProperties/OCGs")
                if kind == "xref":
                    raw = doc.xref_object(int(raw.split()[0]))
                generations = {int(n): int(g) for n, g in re.findall(r"(\d+)\s+(\d+)\s+R", raw)}
                order = "[" + " ".join(f"{n} {generations.get(n, 0)} R" for n in all_refs) + "]"
                doc.xref_set_key(obj, "/".join(key_path + ["Order"]), order)
                data = doc.tobytes()
                doc.close()
                doc = fitz.open(stream=data, filetype="pdf")
                controls = doc.layer_ui_configs()
                if len(controls) != len(all_refs):
                    raise PdfError("visibility_unavailable", "PDF layer configuration cannot be mapped safely to object identities.")
                for control in controls:
                    doc.set_layer_ui_config(control["number"], 2)
                for control, number in zip(controls, all_refs):
                    if number in on:
                        doc.set_layer_ui_config(control["number"], 0)
                actual = doc.layer_ui_configs()
                if any(bool(c["on"]) != (n in on) for c, n in zip(actual, all_refs)):
                    raise PdfError("visibility_unavailable", "Requested layer visibility could not be activated.")
            return doc
        except BaseException:
            doc.close()
            raise

    def pixmap(self, page: int, mode: RenderMode, selected: Sequence[int],
               scale: float, annots: bool = False) -> Pixmap:
        with self.open_view(mode, selected) as doc:
            target = doc[page - 1]
            if math.ceil(target.rect.width * scale) * math.ceil(target.rect.height * scale) > LIMITS["pixels"]:
                raise PdfError("render_limit", f"Render exceeds {LIMITS['pixels']} pixels. Reduce zoom.")
            return target.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB,
                                     alpha=False, annots=annots)


def open_view(path: str | Path, mode: RenderMode = "original", selected: Sequence[int] = ()) -> Document:
    """Compatibility interface for callers that need repeated page renders."""
    return PdfRenderer(path).open_view(mode, selected)


def pixmap(path: str | Path, page: int, mode: RenderMode, selected: Sequence[int],
           scale: float, annots: bool = False) -> Pixmap:
    return PdfRenderer(path).pixmap(page, mode, selected, scale, annots)


def visible(pix: Pixmap) -> VisibleOutput:
    samples = np.frombuffer(pix.samples, dtype=np.uint8).reshape(-1, 3)
    return {"width": pix.width, "height": pix.height,
            "nonwhite_pixels": int(np.count_nonzero(np.any(samples != 255, axis=1)))}


class _ContentInspector:
    """Keep resource traversal, graphics state and attribution in one place.

    Parsed streams live for a single page; decoded-byte accounting and warnings
    live for the document. Form invocations inherit the resolved font object,
    rather than reinterpreting the parent's font name in a child's resources.
    """

    def __init__(self, reader: PdfReader, layers: dict[ObjectReference, Layer],
                 warnings: set[str], restrictions: set[str]) -> None:
        self.reader = reader
        self.layers = layers
        self.warnings = warnings
        self.restrictions = restrictions
        self.decoded = 0
        self.parsed: dict[ObjectReference | int, list[Operation]] = {}
        self.retained_streams: list[object] = []
        self.membership: set[ObjectReference] = set()
        self.per_layer: dict[ObjectReference, ContentCounts] = {}
        self.base = counts()
        self.shared: list[ConditionalOperation] = []

    def inspect(self, stream: object, resources: object) -> None:
        self.parsed.clear()
        self.retained_streams.clear()
        self.membership = set()
        self.per_layer = {key: counts() for key in self.layers}
        self.base = counts()
        self.shared = []
        self._walk(stream, dictionary(resources), [])

    def _incomplete(self, reason: str) -> None:
        self.restrictions.add(reason)
        self.warnings.add(reason)
        for layer in self.layers.values():
            layer["complete"] = False
            layer["warnings"] = sorted(set(layer["warnings"]) | {reason})

    def _condition(self, value: object) -> SourceCondition:
        value = resolve(value)
        if not isinstance(value, dict):
            self.warnings.add("Unresolved optional-content condition; attribution is incomplete.")
            return {"kind": "unknown", "members": []}
        condition = dictionary(value)
        key = ref(value)
        if condition.get("/Type") == "/OCG" and key in self.layers:
            assert key is not None
            return {"kind": "ocg", "members": [key]}
        members: set[ObjectReference] = set()
        self._collect_members(value, members)
        return {"kind": "conditional", "members": sorted(members),
                "expression": self._expression(condition.get("/VE", condition.get("/P", "/AnyOn")))}

    def _collect_members(self, value: object, members: set[ObjectReference], depth: int = 0) -> None:
        if depth > LIMITS["depth"]:
            raise PdfError("nesting_limit", "Optional-content expression exceeds nesting limit.")
        key = ref(value)
        if key in self.layers:
            assert key is not None
            members.add(key)
            return
        value = resolve(value)
        if isinstance(value, list):
            for entry in array(value):
                self._collect_members(entry, members, depth + 1)
        elif isinstance(value, dict):
            for name in ("/OCGs", "/VE"):
                if name in value:
                    self._collect_members(dictionary(value)[name], members, depth + 1)

    def _expression(self, value: object, depth: int = 0) -> ConditionalExpression:
        if depth > LIMITS["depth"]:
            raise PdfError("nesting_limit", "Conditional expression exceeds the nesting limit.")
        if isinstance(value, IndirectObject):
            return {"object": value.idnum, "generation": value.generation}
        if isinstance(value, list):
            return [self._expression(item, depth + 1) for item in array(value)]
        return str(value)

    def _mark(self, context: Sequence[SourceCondition]) -> None:
        for condition in context:
            self.membership.update(condition["members"])

    def _attribute(self, category: Category, context: Sequence[SourceCondition]) -> None:
        self._mark(context)
        members = {key for condition in context for key in condition["members"]}
        if not context:
            self.base[category] += 1
        elif len(members) == 1 and all(condition["kind"] == "ocg" for condition in context):
            self.per_layer[next(iter(members))][category] += 1
        else:
            conditions: list[ManifestCondition] = []
            for condition in context:
                exported: ManifestCondition = {"kind": condition["kind"],
                                               "members": [self.layers[key]["id"] for key in condition["members"]]}
                if "expression" in condition:
                    exported["expression"] = condition["expression"]
                conditions.append(exported)
            self.shared.append({"category": category, "conditions": conditions})
            for key in members or set(self.layers):
                self.layers[key]["complete"] = False
                self.layers[key]["warnings"] = ["Conditional or unresolved content is excluded from exclusive counts."]

    def _operations(self, stream: object, identity: ObjectReference | None) -> list[Operation]:
        stream = resolve(stream)
        if stream is None:
            return []
        cache_key = identity or id(stream)
        if cache_key not in self.parsed:
            self.retained_streams.append(stream)
            # The library parser accepts PDF objects; validate that seam rather
            # than casting its dynamic operand values to application records.
            from pypdf.generic import ArrayObject, NullObject, StreamObject
            if not isinstance(stream, (StreamObject, ArrayObject, NullObject)):
                raise PdfError("invalid_content", "Content is not a PDF stream or stream array.")
            parsed = ContentStream(stream, self.reader)
            size = len(parsed.get_data())
            self.decoded += size
            if size > LIMITS["stream_bytes"] or self.decoded > LIMITS["decoded_bytes"]:
                raise PdfError("decoded_limit", "Decoded content exceeds configured stream/document limits.")
            self.parsed[cache_key] = [(array(args), op) for args, op in parsed.operations]
        return self.parsed[cache_key]

    def _text(self, values: Sequence[object], context: Sequence[SourceCondition], font: PdfDictionary) -> None:
        if not any(isinstance(value, (str, bytes)) and len(value) for value in values):
            return
        self._attribute("text_shows", context)
        members = {key for condition in context for key in condition["members"]}
        if font.get("/Subtype") == "/Type3":
            self._incomplete("Type 3 glyph internals are not structurally attributed; source counts are incomplete and strict solo is unavailable.")
        if len(members) == 1 and all(condition["kind"] == "ocg" for condition in context) and font.get("/BaseFont") in (
            "/Helvetica", "/Helvetica-Bold", "/Times-Roman", "/Times-Bold", "/Courier", "/Courier-Bold"
        ) and font.get("/Encoding", "/StandardEncoding") in ("/StandardEncoding", "/WinAnsiEncoding"):
            sample = " ".join("".join(value for value in values if isinstance(value, str)).split())[:120]
            samples = self.layers[next(iter(members))]["text_samples"]
            if sample and sample.isascii() and sample not in samples and len(samples) < 5:
                samples.append(sample)

    def _walk(self, stream: object, resources: PdfDictionary, inherited: Sequence[SourceCondition],
              chain: tuple[ObjectReference, ...] = (), depth: int = 0,
              inherited_font: PdfDictionary | None = None) -> None:
        if depth > LIMITS["depth"]:
            raise PdfError("nesting_limit", "Content nesting limit exceeded.")
        identity = ref(stream)
        if identity and identity in chain:
            raise PdfError("content_cycle", "Recursive Form content is unsupported.")
        context = list(inherited)
        stack: list[list[SourceCondition]] = []
        graphics: list[PdfDictionary] = []
        font = inherited_font if inherited_font is not None else {}
        path_nonempty = False
        for args, op in self._operations(stream, identity):
            if op == b"BDC":
                stack.append(list(context))
                if args[0] == "/OC":
                    prop = args[1]
                    if isinstance(prop, str):
                        prop = dictionary(resources.get("/Properties")).get(prop)
                    context = context + [self._condition(prop)]
                    self._mark(context)
            elif op == b"BMC":
                stack.append(list(context))
            elif op == b"EMC":
                if not stack:
                    raise PdfError("invalid_content", "Unbalanced marked-content scopes.")
                context = stack.pop()
            elif op == b"q":
                graphics.append(font)
            elif op == b"Q":
                if graphics:
                    font = graphics.pop()
            elif op == b"Tf":
                font = dictionary(dictionary(resources.get("/Font")).get(str(args[0])))
            elif op in (b"scn", b"SCN") and args and isinstance(args[-1], str):
                if args[-1] in dictionary(resources.get("/Pattern")):
                    self._incomplete("Pattern internals are not structurally attributed; source counts are incomplete and strict solo is unavailable.")
            elif op == b"gs":
                state = dictionary(dictionary(resources.get("/ExtGState")).get(str(args[0])))
                if isinstance(resolve(state.get("/SMask")), dict):
                    self._incomplete("Soft-mask internals are not structurally attributed; source counts are incomplete and strict solo is unavailable.")
                state_font = array(state.get("/Font"))
                if state_font:
                    font = dictionary(state_font[0])
            elif op in (b"l", b"c", b"v", b"y", b"re"):
                path_nonempty = True
            elif op in (b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                if path_nonempty:
                    self._attribute("paths", context)
                path_nonempty = False
            elif op == b"n":
                path_nonempty = False
            elif op in (b"Tj", b"TJ", b"'", b'"'):
                values = array(args[0]) if op == b"TJ" else [args[-1]]
                self._text(values, context, font)
            elif op == b"INLINE IMAGE":
                self._attribute("images", context)
            elif op == b"sh":
                self._attribute("shadings", context)
            elif op == b"Do":
                xref = dictionary(resources.get("/XObject")).get(str(args[0]))
                obj = dictionary(xref)
                if not obj:
                    raise PdfError("invalid_content", "An XObject resource cannot be resolved.")
                child_context = list(context)
                if "/OC" in obj:
                    child_context.append(self._condition(obj["/OC"]))
                    self._mark(child_context)
                if obj.get("/Subtype") == "/Image":
                    self._attribute("images", child_context)
                elif obj.get("/Subtype") == "/Form":
                    self._walk(xref, dictionary(obj.get("/Resources", resources)), child_context,
                               chain + ((identity,) if identity else ()), depth + 1, font)
                else:
                    raise PdfError("unsupported_xobject", "Unsupported XObject subtype.")
        if stack:
            raise PdfError("invalid_content", "Unclosed marked-content scopes.")


def _no_progress(stage: str, completed: int, total: int) -> None:
    pass


class PdfAnalyzer:
    """Analyze one immutable source into deterministic, JSON-shaped facts."""

    def __init__(self, path: str | Path, digest: str, progress: ProgressCallback = _no_progress) -> None:
        self.path = Path(path)
        self.digest = digest
        self.progress = progress
        self.warnings: set[str] = set()
        self.restrictions: set[str] = set()

    def _order(self, value: object, result: list[ObjectReference], depth: int = 0) -> None:
        if depth > LIMITS["depth"]:
            raise PdfError("nesting_limit", "Layer order exceeds the nesting limit.")
        for item in array(value):
            if isinstance(resolve(item), list):
                self._order(item, result, depth + 1)
            else:
                key = ref(item)
                if key is not None and key not in result:
                    result.append(key)

    def _layers(self, reader: PdfReader) -> dict[ObjectReference, Layer]:
        oc = dictionary(dictionary(reader.trailer["/Root"]).get("/OCProperties"))
        config = dictionary(oc.get("/D"))
        if oc.get("/Configs") or config.get("/RBGroups") or config.get("/Locked") or config.get("/AS"):
            self.warnings.add("Alternate, locked, or radio-group configurations restrict custom visibility.")
        off_refs = {ref(item) for item in array(config.get("/OFF"))}
        on_refs = {ref(item) for item in array(config.get("/ON"))}
        source_order: list[ObjectReference] = []
        self._order(config.get("/Order"), source_order)
        layers: dict[ObjectReference, Layer] = {}
        for order, item in enumerate(array(oc.get("/OCGs"))):
            key = ref(item)
            if key is None:
                raise PdfError("unsupported_ocg", "A native layer has no indirect object identity.")
            obj = dictionary(item)
            layers[key] = {"id": f"{self.digest}:{key[0]}:{key[1]}", "name": str(obj.get("/Name", "")),
                           "object_reference": {"number": key[0], "generation": key[1]},
                           "source_order": source_order.index(key) if key in source_order else len(source_order) + order,
                           "default_visible": key in on_refs or (config.get("/BaseState", "/ON") != "/OFF" and key not in off_refs),
                           "referenced_pages": [], "content_pages": [], "counts": counts(),
                           "complete": True, "warnings": [], "page_details": [], "text_samples": [],
                           "source_empty": None, "source_operations": 0, "explanation": ""}
        return layers

    def analyze(self) -> AnalysisManifest:
        self.warnings.clear()
        self.restrictions.clear()
        try:
            reader = PdfReader(self.path, strict=False)
        except Exception as exc:
            raise PdfError("invalid_pdf", "The file is not a readable PDF.") from exc
        if reader.is_encrypted:
            raise PdfError("encrypted_pdf", "Encrypted PDFs are unsupported. Upload a decrypted local copy.")
        if not 0 < len(reader.pages) <= LIMITS["pages"]:
            raise PdfError("page_limit", f"PDF must have 1–{LIMITS['pages']} pages.")
        layers = self._layers(reader)
        pages: list[PageFacts] = []
        base_pages: list[BaseContent] = []
        conditional: list[ConditionalContent] = []
        inspector = _ContentInspector(reader, layers, self.warnings, self.restrictions)
        with fitz.open(str(self.path)) as doc:
            for index, page in enumerate(reader.pages):
                number = index + 1
                self.progress("Inspecting source operations", index, len(reader.pages))
                inspector.inspect(page.get_contents(), page.get_inherited("/Resources", {}))
                target = doc[index]
                annotations = [dictionary(item) for item in array(page.get("/Annots"))]
                annotation_types = Counter(str(item.get("/Subtype", "unknown")) for item in annotations)
                layer_annotations = sum(1 for item in annotations if "/OC" in item)
                shx_annotations = sum(1 for item in annotations if str(item.get("/T", "")) == "AutoCAD SHX Text")
                if layer_annotations:
                    self.warnings.add("Layer-associated annotations are excluded from default previews and source counts.")
                pages.append({"page": number, "label": target.get_label(), "rotation": target.rotation,
                              "media_box": list(target.mediabox), "crop_box": list(target.cropbox),
                              "width": target.rect.width, "height": target.rect.height,
                              "layers": [layers[key]["id"] for key in sorted(inspector.membership)],
                              "annotations": dict(sorted(annotation_types.items())), "layer_annotations": layer_annotations,
                              "shx_annotation_count": shx_annotations})
                base_pages.append({"page": number, "counts": inspector.base})
                if inspector.shared:
                    conditional.append({"page": number, "operations": inspector.shared})
                for key in sorted(inspector.membership):
                    layer = layers[key]
                    layer["referenced_pages"].append(number)
                    per_page = inspector.per_layer[key]
                    if operation_total(per_page):
                        layer["content_pages"].append(number)
                    for category in CATEGORIES:
                        layer["counts"][category] += per_page[category]
                    layer["page_details"].append({"page": number, "counts": per_page, "bounds": None,
                                                  "visible_output": None, "source_empty": None, "complete": True})
        base_present = any(operation_total(page["counts"]) for page in base_pages)
        custom_visibility = not any("configurations" in warning for warning in self.warnings)
        strict = not base_present and not conditional and not self.restrictions and custom_visibility
        self._visibility(layers, strict)
        modes: list[RenderMode] = ["original"]
        if custom_visibility:
            modes.extend(["all-on", "all-off", "selected"])
        if strict:
            modes.append("solo")
        body: AnalysisBody = {
            **profile(), "source_sha256": self.digest,
            "measurement": "Source operations: nonempty path paints (combined fill/stroke counts once), nonempty text shows, image placements, and shadings; not CAD entities. Visibility is measured separately at 36 DPI.",
            "document": {"bytes": self.path.stat().st_size, "pdf_version": reader.pdf_header,
                         "page_count": len(pages), "has_layers": bool(layers), "encrypted": False,
                         "annotation_count": sum(sum(page["annotations"].values()) for page in pages),
                         "shx_annotation_count": sum(page["shx_annotation_count"] for page in pages)},
            "pages": pages, "layers": [value for _, value in sorted(layers.items())],
            "base_content": base_pages, "conditional_content": conditional,
            "capabilities": {"strict_solo": strict, "base_content_present": base_present,
                             "custom_visibility": custom_visibility, "modes": modes},
            "warnings": sorted(self.warnings),
        }
        return {**body, "analysis_identity": hashlib.sha256(canonical(body)).hexdigest()}

    def _visibility(self, layers: dict[ObjectReference, Layer], strict: bool) -> None:
        renderer = PdfRenderer(self.path)
        for ordinal, (key, layer) in enumerate(sorted(layers.items())):
            self.progress("Measuring layer visibility", ordinal, len(layers))
            with renderer.open_view("solo" if strict else "original", [key[0]]) as isolated:
                for detail in layer["page_details"]:
                    if strict:
                        target = isolated[detail["page"] - 1]
                        if math.ceil(target.rect.width / 2) * math.ceil(target.rect.height / 2) > LIMITS["pixels"]:
                            raise PdfError("render_limit", "Visibility profile exceeds the render pixel budget.")
                        detail["visible_output"] = visible(target.get_pixmap(matrix=fitz.Matrix(.5, .5), colorspace=fitz.csRGB,
                                                                            alpha=False, annots=False))
                    detail["source_empty"] = operation_total(detail["counts"]) == 0 if layer["complete"] else None
                    detail["complete"] = layer["complete"]
            total = operation_total(layer["counts"])
            layer["source_empty"] = total == 0 if layer["complete"] else None
            layer["source_operations"] = total
            layer["text_samples"].sort()
            layer["explanation"] = (
                f"Referenced on {len(layer['referenced_pages'])} pages; {total} exclusively attributed source operations: "
                f"{layer['counts']['paths']} path paints, {layer['counts']['text_shows']} text shows, "
                f"{layer['counts']['images']} image placements, {layer['counts']['shadings']} shadings. "
                + ("Source inspection is complete. " if layer["complete"] else "Conditional attribution is incomplete. ")
                + ("Directly attributable text samples: " + "; ".join(layer["text_samples"]) + ". " if layer["text_samples"] else "No reliably decoded, directly attributable text samples are available. ")
                + "No purpose is inferred from the name.")


def analyze(path: str | Path, digest: str, progress: ProgressCallback = _no_progress) -> AnalysisManifest:
    return PdfAnalyzer(path, digest, progress).analyze()
