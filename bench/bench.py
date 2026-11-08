"""Time the six layout comparisons on the bundled captures, then a whole compare with reports. Usage: python bench/bench.py"""
import statistics, sys, tempfile, time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rebuild_proof as r

cap = r.HERE / "examples" / "captures"
pairs = [(np.array(Image.open(cap / "original" / f"screenshot-{w}.png").convert("RGB")), np.array(Image.open(cap / b / f"screenshot-{w}.png").convert("RGB"))) for w in (1280, 768, 390) for b in ("first-try", "fixed")]
six, whole = [], []
with tempfile.TemporaryDirectory() as d:
    for _ in range(5):
        t = time.perf_counter()
        for a, b in pairs:
            r.diff_pictures(a, b)
        six.append(time.perf_counter() - t)
        t = time.perf_counter()
        r.compare(cap / "original", cap / "first-try", d)
        whole.append(time.perf_counter() - t)
print(f"six layout comparisons: median {statistics.median(six) * 1000:.0f} ms. Whole compare with report, three widths: median {statistics.median(whole) * 1000:.0f} ms ({len(six)} runs)")
