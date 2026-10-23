"""Isolated frontend regressions; synthetic HTTP data, not product acceptance.

Run: uv run python tests/browser_review.py
Serves only local static assets on an ephemeral port and intercepts every request
to /api/. This runner never connects to the retained application's document store.
"""
from __future__ import annotations

import base64
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import Browser, Page, Route, expect, sync_playwright


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jc1sAAAAASUVORK5CYII="
)


def manifest(document: str) -> dict[str, object]:
    counts = {"paths": 1, "text_shows": 0, "images": 0, "shadings": 0}
    return {
        "layers": [{
            "id": f"{document}-layer", "name": f"Layer {document}",
            "default_visible": True, "object_reference": {"number": 5, "generation": 0},
            "referenced_pages": [1], "content_pages": [1], "source_operations": 1,
            "source_order": 0, "counts": counts, "source_empty": False,
            "explanation": f"Evidence for drawing {document}",
            "page_details": [{"page": 1, "counts": counts, "visible_output": {
                "nonwhite_pixels": 1, "width": 1, "height": 1,
            }}],
        }],
        "document": {"page_count": 1, "pdf_version": "1.7", "annotation_count": 0,
                     "shx_annotation_count": 0, "has_layers": True},
        "pages": [{"page": 1, "width": 100, "height": 100, "label": "1"}],
        "capabilities": {"strict_solo": True, "custom_visibility": True,
                         "base_content_present": False},
        "warnings": [],
    }


class SyntheticDocuments:
    def __init__(self, base: str) -> None:
        self.base = base
        self.documents = ["A", "B", "Broken"]
        self.hold_a = False
        self.fail_a = False
        self.held: list[Route] = []

    @staticmethod
    def fulfill(route: Route, body: object, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def route(self, route: Route) -> None:
        path = route.request.url.removeprefix(self.base)
        if path == "/api/documents":
            self.fulfill(route, [{"id": item, "filename": f"{item}.pdf", "size": 100,
                                  "state": "failed" if item == "Broken" else "succeeded"}
                                 for item in self.documents])
        elif route.request.method == "DELETE":
            self.documents.remove(path.split("/")[3])
            route.fulfill(status=204)
        elif path == "/api/documents/A/status" and self.hold_a:
            self.held.append(route)
        elif path == "/api/documents/A/status" and self.fail_a:
            self.fulfill(route, {"error": {"message": "Current A request failed"}}, 500)
        elif path.endswith("/status"):
            item = path.split("/")[3]
            self.fulfill(route, {"id": item, "filename": f"{item}.pdf", "size": 100,
                                 "state": "failed" if item == "Broken" else "succeeded",
                                 "stage": "ready", "total": 0,
                                 "error": {"message": "Broken source"} if item == "Broken" else None})
        elif path.endswith("/analysis"):
            self.fulfill(route, manifest(path.split("/")[3]))
        elif path.endswith("/renders"):
            self.fulfill(route, {"url": "/api/renders/synthetic", "state": "succeeded"})
        elif path.startswith("/api/renders/"):
            route.fulfill(status=200, content_type="image/png", body=PNG)
        else:
            raise AssertionError(f"Unexpected synthetic request: {route.request.method} {path}")


def open_document(page: Page, document: str) -> None:
    page.locator(".document", has_text=f"{document}.pdf").click()
    expect(page.locator("#filename")).to_have_text(f"{document}.pdf")
    expect(page.locator("#results")).to_be_visible()


def check_document_resets(browser: Browser, base: str) -> None:
    page = browser.new_page()
    fake = SyntheticDocuments(base)
    page.route("**/api/**", fake.route)
    page.goto(base)
    open_document(page, "A")
    page.locator(".layer-name").click()
    expect(page.locator("#details")).to_contain_text("Evidence for drawing A")
    open_document(page, "B")
    expect(page.locator("#details h3")).to_have_text("Inspect a layer")
    expect(page.locator("#details")).not_to_contain_text("Evidence for drawing A")
    page.locator(".layer-name").click()
    expect(page.locator("#details")).to_contain_text("Evidence for drawing B")
    print("PASS: switching documents clears the previous layer's evidence")

    page.locator(".document", has_text="Broken.pdf").click()
    expect(page.locator("#retry")).to_be_visible()
    page.locator("#delete").click()
    page.locator("#confirm-delete-button").click()
    expect(page.locator("#notice")).to_contain_text("deleted")
    expect(page.locator("#retry")).to_be_hidden()
    expect(page.locator("#delete")).to_be_disabled()
    expect(page.locator("#drawing")).to_be_hidden()
    expect(page.locator("#details h3")).to_have_text("Inspect a layer")
    print("PASS: deleting a failed document clears its retry control")
    page.close()


def check_stale_failure(browser: Browser, base: str) -> None:
    page = browser.new_page()
    fake = SyntheticDocuments(base)
    fake.hold_a = True
    page.route("**/api/**", fake.route)
    page.goto(base)
    expect(page.locator(".document", has_text="A.pdf")).to_be_visible()
    # Record the actual handler's settlement so the late-error assertion cannot
    # pass merely because its rejected request has not reached the guard yet.
    page.evaluate("""() => {
        const button = [...document.querySelectorAll('.document')].find(node => node.textContent.includes('A.pdf'));
        const handler = button.onclick;
        button.onclick = (...args) => Promise.resolve(handler(...args)).finally(() => {
            document.documentElement.dataset.reviewASettled = 'true';
        });
    }""")
    with page.expect_request("**/api/documents/A/status"):
        page.locator(".document", has_text="A.pdf").click()
    open_document(page, "B")
    assert len(fake.held) == 1
    with page.expect_response("**/api/documents/A/status"):
        fake.fulfill(fake.held.pop(), {"error": {"message": "Stale A request failed"}}, 500)
    page.wait_for_function("document.documentElement.dataset.reviewASettled === 'true'")
    expect(page.locator("#filename")).to_have_text("B.pdf")
    expect(page.locator("#notice")).to_contain_text("Analysis ready")
    expect(page.locator("#notice")).not_to_have_class("error")

    fake.hold_a = False
    fake.fail_a = True
    page.locator(".document", has_text="A.pdf").click()
    expect(page.locator("#notice")).to_have_text("Current A request failed")
    expect(page.locator("#notice")).to_have_class("error")
    print("PASS: stale opening failures are ignored; current failures remain visible")
    page.close()


def main() -> None:
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(static)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                check_document_resets(browser, base)
                check_stale_failure(browser, base)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print("3 isolated frontend regressions passed; PDF/backend acceptance was not exercised.")


if __name__ == "__main__":
    main()
