---
name: app-parity
description: Score how much of the original's job a build does, and what to build next. Use when the user asks what's missing or whether it's ready.
---

# app-parity

```bash
python rebuild_proof.py parity docs/screens/features.csv --layout proof/*/report.json
```

Must counts 3, should 2, could 1, partial half. Skipped rows and features the original lacks are left out. Overall is 80% features and 20% layout. Exit code 1 means not shippable.

**Not shippable** means a must-have is missing or features are under 80%. Report the number as it is. Build the missing list from the top, and do not mark a row `yes` until you have used the feature.
