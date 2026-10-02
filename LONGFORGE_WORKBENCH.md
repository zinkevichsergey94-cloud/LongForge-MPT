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
- YouTube Safe Mode with SAFE / REVIEW / DO NOT USE classification
- hard export gate for unresolved rights issues (enabled by default)
- downloadable copyright review report before DaVinci export

## Next engineering steps

- waveform/audio timing so shot durations can be aligned to the final narration automatically
- richer archive connectors and source-level filters
- proxy/preview generation for faster browsing
- range selection (in/out points) for long source clips
- drag-and-drop timeline UI
- DaVinci round-trip metadata and optional Resolve scripting bridge

## YouTube Safe Mode

Safe Mode is enabled by default. It screens each selected asset conservatively:

- **SAFE** — stock/provider-license path, public domain/CC0, or attribution-only CC BY metadata.
- **REVIEW** — rights are not machine-verifiable (for example a local upload) or the license has conditions that need a manual check.
- **DO NOT USE** — metadata indicates non-commercial/no-derivatives/editorial-only/all-rights-reserved or otherwise does not grant reuse rights.

When Safe Mode is on, DaVinci export is disabled until every selected shot is SAFE. REVIEW assets can become SAFE only after the user explicitly confirms that the rights/license were checked. DO NOT USE search results cannot be selected from Media Scout. A copyright CSV can be downloaded before export and is also included in the final export package.

This is a conservative production guardrail, not a legal opinion or a guarantee against Content ID claims.
