---
name: app-stories
description: Turn captured screens into a backlog and a feature matrix. Use after app-recon, or when the user asks for user stories from screenshots.
---

# app-stories

```bash
python rebuild_proof.py stories captures/original --out docs/screens
```

This writes `INDEX.md`, `STORIES.md` and `features.csv`. They are a first draft from what was visible:

1. Try each action in the original, and replace each `[manual]` line with what actually happens.
2. Add what a capture cannot see: search, saving, emails, errors, what is remembered.
3. In `features.csv`, set `priority` to must, should or could. Must means the app is useless without it. Keep musts to the smallest set that does the job.
4. Set `clone` to `skip` with a reason for anything licensed or out of scope.
