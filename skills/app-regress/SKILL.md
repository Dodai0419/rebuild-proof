---
name: app-regress
description: Catch what changed between two versions of your own build. Use before a release, or when the user asks what a change broke.
---

# app-regress

Capture your own build before and after the change, then compare:

```bash
python rebuild_proof.py capture http://localhost:3000/ --out captures/before
python rebuild_proof.py capture http://localhost:3000/ --out captures/after
python rebuild_proof.py compare captures/before captures/after --out proof/regress --bar 98
```

Between two versions of the same app, "exact pixels" is the number to read, and it should be close to 100. Look at any width where it drops, and at the red cells in the report. Dates and random data will show up: fix them in the test data first.
