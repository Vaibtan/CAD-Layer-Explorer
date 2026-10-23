# CAD-Layer-Explorer

A local web app for exploring native layers in CAD-exported PDFs. Upload a drawing, inspect its layers and content counts, view layers independently, and export the analysis as JSON. All drawing data stays on your machine.

## Architecture

The browser uses plain HTML, CSS, and JavaScript. FastAPI serves the interface and API, while a supervised PDF process handles analysis and rendering inside the local application container.

```mermaid
flowchart TB
    subgraph Machine["User's machine - all drawing data stays local"]
        UI["Browser interface<br/>Upload - page navigation - layer toggles<br/>Drawing viewer - table - JSON export"]

        subgraph Docker["Local application container"]
            API["FastAPI<br/>Serve frontend - validate uploads<br/>Expose analysis, status and previews"]
            Supervisor["Job supervisor<br/>Bounded queue - timeouts - cancellation<br/>One active PDF child process"]

            subgraph Worker["Disposable PDF child process"]
                Inspect["pypdf analysis<br/>Layer identities - page membership<br/>Source counts - empty-layer detection"]
                Render["PyMuPDF rendering<br/>Original - solo - selected layers<br/>Visibility checks - PNG previews"]
            end
        end

        subgraph Storage["Persistent local storage"]
            PDF[("Immutable source PDFs<br/>Identified by SHA-256")]
            Manifest[("Canonical analysis JSON<br/>Counts - explanations - capabilities")]
            Cache[("Preview cache<br/>Page + visibility + render settings")]
            DB[("SQLite<br/>Documents - jobs - operational status")]
        end

        UI <-->|"Loopback HTTP: requests, status, JSON and PNG"| API
        API -->|"Store validated upload"| PDF
        API -->|"Request analysis or render"| Supervisor
        Supervisor <-->|"Queue and job state"| DB
        Supervisor -->|"Analysis job"| Inspect
        Supervisor -->|"Render or visibility-check job"| Render
        PDF -->|"Read source"| Inspect
        PDF -->|"Read source"| Render
        Render -.->|"Visibility evidence"| Inspect
        Inspect -->|"Publish atomically through supervisor"| Manifest
        Render -->|"Publish through supervisor"| Cache
        Manifest -->|"Shared data for table and JSON"| API
        Cache -->|"Cached preview"| API
    end
```

The canonical manifest supplies both the table and JSON export. Layer identities use the document hash and PDF object reference, so duplicate names remain distinct. Source emptiness and visible output are measured separately.

PDF work runs outside the API process with bounded resources. Original PDFs and completed analyses persist until deletion; previews are cached and can be regenerated.
