# Generated reports

Sample and check output — every file here is regenerable and git-ignored, so
delete the lot whenever it gets stale.

| Producer | Writes |
|---|---|
| `scripts/run_query.py --export markdown\|json\|html\|render\|pdf` | `report-<query-prefix>.<ext>` |
| `tests/integration/live_v2_socket.py` | `nodus-<query-prefix>.pdf` |
| `tests/integration/live_pipeline_stream.py` | `nodus-<query-prefix>.pdf` |
| `tests/integration/render_screenshots.py` | `screen-<theme>.png`, `print.png` |

Two exports of the same report are not interchangeable:

- `html` is the plain print-CSS export from `app/services/export.py` — the
  no-dependency **Print → Save as PDF** path.
- `render` is the document the frontend shows, from
  `app/services/report_render.py`: ranked cluster rail, quality-tier chips,
  lineage timelines, claim tables, light and dark themes.
- `pdf` is the *print variant* of `render`, rendered in headless Chromium — the
  same design, single column, forced light palette, disclosures expanded.

Point a producer somewhere else with `--out-dir` (or `--out` for screenshots).
