---
name: rebuild-proof
description: Rebuild a web app you like as your own, step by step, and prove how close you got. Use when the user says clone this app, rebuild this site, make my own version of X, or asks how close their rebuild is.
---

# rebuild-proof

Find where the user is, then use the right skill. Run the tool from the repo root.

| They have | Next skill |
|-----------|------------|
| Only the name or URL of an app | `app-recon` |
| Captures of the original | `app-stories` |
| A backlog, no design values | `app-measure` |
| A backlog and values, no build | `app-rebuild` |
| A build | `app-compare` |
| A build with a layout score | `app-parity` |
| A shippable build | `app-own-it`, then `app-better` |
| Something that broke between versions | `app-regress` |

Try it with no browser: `python rebuild_proof.py demo`

Rebuild what an app does, never what it owns: not its code, logo, copy or content. Only capture pages the user may view, and respect a site's terms.
