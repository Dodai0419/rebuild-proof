---
name: app-compare
description: Score a build's layout against the original and list what to fix. Use when the user asks how close it is or wants a side-by-side.
---

# app-compare

```bash
python rebuild_proof.py compare captures/original/home captures/build/home --out proof/home
```

Exit code 1 means under the bar. `proof/home/report.html` shows the original, the build and where the layout differs, at each width.

- **Layout** compares edge density on a grid and ignores color, so your own brand is not punished. 90+ is a match, 75+ is close. The default bar is 80, because your own words shift the edges a little.
- **Exact pixels** is shown for information. Do not chase it against the original.
- Capture both in the same state: same viewport, same data shape, same tab open. A mismatch here looks like a layout bug.
