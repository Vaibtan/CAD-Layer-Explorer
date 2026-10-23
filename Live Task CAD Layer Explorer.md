# Live Task: CAD Layer Explorer

**Live Technical Task**\
**Date:** Oct 23, 2026\
**Source:** [Live Task CAD Layer Explorer.pdf](<Live Task CAD Layer Explorer.pdf>)

Build a small web app that reads a CAD-exported PDF drawing, extracts its layers, shows each layer on its own, and explains what each layer contains.

## Background

Architectural and structural drawings are made in CAD tools such as AutoCAD. In CAD, every element is drawn on a named layer, so walls, doors, dimensions and text can be shown, hidden or styled separately.

When these drawings are exported to PDF, the layers are often kept inside the file. You can see them in a PDF viewer's layers panel and switch them on and off.

Some layers carry the important drawing content, some support it, and some are just noise, such as empty layers or the sheet border. Layer names are set by whoever made the drawing, so they are not always consistent or clear.

## The task

Build a web app that does the following with the drawing we give you:

1. Upload the PDF and show basic file information, including whether it has layers.
2. Extract all layers in the file.
3. Show details for each layer: which pages it appears on, how much content it has, and whether it is empty.
4. Render each layer on its own, so the user sees only that layer's content.
5. Present the results for each layer in a proper table and in JSON format, with the layer name and its details (pages, amount of content, empty or not, and anything else useful).
6. Show it all in a frontend where the user can browse pages, view layers one by one, and toggle them on and off over the full drawing.

You don't need to finish everything. Start with a simple version that works end to end, then improve it.

## Requirements

- The same file must always give the same results.
- The table and the JSON must show the same data.
- The drawing must stay on your machine. Do not upload it to any external service.
- The app should handle files without layers, empty layers and large drawings without crashing.
- Use any language, framework or open-source library you like.

## What we provide

We provide the drawing file (`cader_structural.pdf`, a 38-page structural drawing set) at the start of the session.
