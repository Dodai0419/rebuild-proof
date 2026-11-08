---
name: app-rebuild
description: Build a web app screen by screen from a backlog. Use when the user has stories and measured values and asks to build the rebuild.
---

# app-rebuild

1. Pick the stack the user already knows. Ask only if nothing suggests one.
2. Build one story at a time, musts first. Write your own code and words: never copy the original's source, assets or text.
3. After each screen, capture it and compare it:
   ```bash
   python rebuild_proof.py capture http://localhost:3000/ --out captures/build/home
   python rebuild_proof.py compare captures/original/home captures/build/home --out proof/home
   ```
4. Do the first item on the "fix" list, and repeat until it passes. Then set `Status: done` in `STORIES.md` and `clone` to `yes` in `features.csv`.
