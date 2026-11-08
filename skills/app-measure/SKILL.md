---
name: app-measure
description: Read exact colors, rows and spacing from a screenshot. Use before writing styles for a rebuild, or when a layout looks close but not right.
---

# app-measure

```bash
python rebuild_proof.py measure captures/original/home/screenshot-1280.png
```

It prints the size, background, colors with their shares, each row's position, the usual gap and the left edge.

- Use the rows, gaps and left edge as they are: that is what makes a layout feel right.
- Use the colors to learn the roles (background, surface, accent), then choose your own values for those roles.
- Write the values into one place, such as CSS variables, before building any screen.
