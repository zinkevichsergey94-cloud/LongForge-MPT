# LongForge Documentary Workbench

This branch starts the post-Pictory architecture for LongForge.

## Core idea

LongForge no longer tries to silently generate a finished faceless video from keywords. The workflow is deliberately editor-led:

1. Paste/write narration.
2. Turn it into editable shots.
3. Search each shot independently across stock and open/public sources.
4. Review the exact candidates and their provenance/license metadata.
5. Choose the media that belongs in the documentary.
6. Keep the chosen shots in an explicit ordered timeline.
7. Export FCPXML for DaVinci Resolve plus a JSON timeline manifest and source/license CSV.

The existing MoneyPrinterTurbo code is retained as a donor library for search, download, rendering and provider integrations. The new workbench is isolated in `longforge/` and `longforge_app.py` so the old UI remains available for comparison/fallback.

## Run on Windows

Double-click `longforge.bat` (or run it from a terminal). Default address: `http://127.0.0.1:8510`.

## Run on macOS/Linux

```bash
./longforge.sh
```

## Current MVP

- local project persistence under `storage/longforge_projects/`
- paragraph/sentence based shot planning
- per-shot editable narration, search query, duration and notes
- Universal Media Scout reuse (Pexels, Pixabay, Coverr, Wikimedia Commons, Openverse, Internet Archive)
- manual candidate selection instead of automatic assembly
- user-supplied local media per shot
- ordered shot timeline with up/down controls
- DaVinci-compatible FCPXML handoff
- JSON timeline manifest
- source/license CSV

## Next engineering steps

- waveform/audio timing so shot durations can be aligned to the final narration automatically
- richer archive connectors and source-level filters
- proxy/preview generation for faster browsing
- range selection (in/out points) for long source clips
- drag-and-drop timeline UI
- DaVinci round-trip metadata and optional Resolve scripting bridge
