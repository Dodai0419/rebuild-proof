#!/usr/bin/env python3
"""rebuild-proof: study an app you like from the outside, build your own version, and prove how close you got.

The layout diff and the feature parity score are ported from Jakeschincariol/replica-skill (MIT). The screens-to-stories
flow and the measuring come from daveebbelaar/bama (MIT). Needs Pillow and numpy, plus Edge or Chrome for `capture`.
"""
import argparse, base64, csv, html, io, json, os, re, shutil, subprocess, sys, tempfile, time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
WIDTHS = (1280, 768, 390)
GOOD = 80.0  # your own words and colors keep a rebuild from reaching 100: replica-skill calls 75+ close and 90+ a match
SKIP = {"script", "style", "noscript", "template", "svg", "head", "title", "meta", "link"}
PARTS = {"header", "nav", "main", "footer", "aside", "form", "ul", "ol", "table", "img", "video", "button", "input", "select", "textarea", "h1", "h2", "h3", "h4", "section"}
VOID = {"img", "input", "br", "hr", "meta", "link", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


# ---------- capture: what a visitor sees, at three widths ----------
class _Dom(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.headings, self.outline, self.actions, self.stack, self.skip = [], [], [], [], [], 0
        self.title, self.grab = "", None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.grab = ["title", []]
        if tag in SKIP and tag != "head":
            if tag not in VOID:
                self.skip += 1
            return
        if self.skip:
            return
        if tag == "a":
            self.outline.append("link")
        elif tag in PARTS:
            self.outline.append(tag)
        if tag in ("h1", "h2", "h3", "h4", "button", "a"):
            self.grab = [tag, []]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "title" and self.grab and self.grab[0] == "title":
            self.title = "".join(self.grab[1]).strip()
            self.grab = None
        if tag in SKIP and tag not in VOID and tag != "head":
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or not self.grab or self.grab[0] != tag:
            return
        words = " ".join("".join(self.grab[1]).split())
        if words:
            (self.headings if tag[0] == "h" else self.actions).append(words)
        self.grab = None

    def handle_data(self, data):
        if self.grab and self.grab[0] == "title":
            self.grab[1].append(data)
        if self.skip:
            return
        self.text.append(data)
        if self.grab:
            self.grab[1].append(data)


def parse_dom(markup):
    p = _Dom()
    p.feed(markup)
    return {"title": p.title, "text": " ".join(" ".join(p.text).split()), "headings": p.headings, "outline": p.outline, "actions": p.actions}


def target_url(target):
    if re.match(r"https?://", target):
        return target
    if re.match(r"[a-z][a-z0-9+.-]+:", target, re.I) and not re.match(r"[a-z]:[\\/]", target, re.I):
        raise ValueError(f"only http, https and local HTML files can be captured, not {target}")
    p = Path(target)
    if not p.is_file():
        raise ValueError(f"no such file: {target}")
    return p.resolve().as_uri()


def find_browser():
    pf = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    candidates = [os.environ.get("BROWSER_PATH", ""), shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    candidates += [str(Path(b, s)) for b in pf if b for s in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe")]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise RuntimeError("no Edge or Chrome found. Install one, or set BROWSER_PATH, or take your own screenshots named screenshot-<width>.png.")


def _headless(browser, url, *flags, wait_for=None, timeout=90):
    """Headless browsers can hang on exit, so once the file is written and stable the process is stopped."""
    profile = tempfile.mkdtemp(prefix="rebuild-proof-")
    cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", f"--user-data-dir={profile}", "--virtual-time-budget=6000", *flags, url]
    with tempfile.TemporaryFile() as out:
        p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.DEVNULL)
        end = time.monotonic() + timeout
        try:
            while time.monotonic() < end and p.poll() is None:
                if wait_for and Path(wait_for).exists() and time.time() - Path(wait_for).stat().st_mtime > 2:
                    break
                time.sleep(0.3)
        finally:
            p.kill()
            p.wait()
            shutil.rmtree(profile, ignore_errors=True)
        out.seek(0)
        return out.read().decode("utf-8", errors="replace")


def capture(target, out, widths=WIDTHS, height=1400):
    url, browser, out = target_url(target), find_browser(), Path(out).resolve()  # the browser runs from its own folder
    out.mkdir(parents=True, exist_ok=True)
    shots = []
    for w in widths:
        f = out / f"screenshot-{w}.png"
        f.unlink(missing_ok=True)
        _headless(browser, url, f"--window-size={w},{height}", f"--screenshot={f}", wait_for=f)
        if not f.exists():
            raise RuntimeError(f"the browser wrote no screenshot at {w} px")
        shots.append(f)
    info = parse_dom(_headless(browser, url, "--dump-dom", "--window-size=1280,1400"))
    info["url"] = target
    (out / "capture.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    return shots


# ---------- layout and pixels (numpy port of replica-skill's imgdiff.py; same indexes, thresholds and grid) ----------
def _to_width(arr, target):
    h, w = arr.shape[:2]
    if w == target:
        return arr
    new_h = max(1, int(round(h * target / float(w))))
    return arr[(np.arange(new_h) * h // new_h)[:, None], np.arange(target) * w // target]


def _gray(a):
    a = a.astype(np.int32)
    return (299 * a[..., 0] + 587 * a[..., 1] + 114 * a[..., 2]) // 1000


def _edges(g, threshold):
    right = np.concatenate([g[:, 1:], g[:, -1:]], axis=1)
    below = np.concatenate([g[1:], g[-1:]], axis=0)
    return (np.abs(right - g) + np.abs(below - g)) > threshold


def _sum_blocks(a, n, cols):
    ys, xs = np.arange(0, a.shape[0], n), np.arange(cols) * n
    return np.add.reduceat(np.add.reduceat(a, ys, axis=0), xs, axis=1)


def diff_pictures(a, b, width=480, cols=12, tolerance=24, edge_threshold=40):
    """Layout: compares edge density cell by cell, ignores color, and scores only cells with something in them.
    Pixels: the share within tolerance, for your own regressions rather than for chasing the original."""
    target = min(width, a.shape[1], b.shape[1])
    pa, pb = _to_width(a, target), _to_width(b, target)
    delta = (pb.shape[0] - pa.shape[0]) / pa.shape[0] * 100 if pa.shape[0] else 0.0
    h = min(pa.shape[0], pb.shape[0])
    pa, pb = pa[:h], pb[:h]
    cell = max(1, target // cols)
    use = pa.shape[1] - pa.shape[1] % cell if target >= cols else target
    n_cols = use // cell
    ea, eb = _edges(_gray(pa), edge_threshold)[:, :use].astype(float), _edges(_gray(pb), edge_threshold)[:, :use].astype(float)
    area = _sum_blocks(np.ones(ea.shape), cell, n_cols)
    da, db = _sum_blocks(ea, cell, n_cols) / area, _sum_blocks(eb, cell, n_cols) / area
    top = np.maximum(da, db)
    busy = top >= 0.01
    sims = np.ones(top.shape)
    sims[busy] = 1 - np.abs(da[busy] - db[busy]) / top[busy]
    layout = float(sims[busy].mean()) * 100 if busy.any() else 100.0
    changed = np.abs(pa.astype(int) - pb.astype(int)).max(axis=2) > tolerance
    return {"layout": layout, "pixel": 100 * (1 - float(changed.mean())), "height_delta_pct": delta, "flags": busy & (sims < 0.6), "cell": cell, "at": (pa, pb)}


def where_most(flags):
    """Name the part of the page with the most cells that differ, the way a person would."""
    if not flags.any():
        return None
    rows, cols = np.where(flags)
    v = ("top", "middle", "bottom")[min(2, int(np.median(rows) / max(1, flags.shape[0] - 1) * 3))]
    hz = ("left", "centre", "right")[min(2, int(np.median(cols) / max(1, flags.shape[1] - 1) * 3))]
    return f"{v} {hz}"


def heat(d):
    pa, _ = d["at"]
    base = _gray(pa)[..., None].repeat(3, 2) * 0.35 + 150
    big = np.kron(d["flags"], np.ones((d["cell"], d["cell"]), bool))[:pa.shape[0], :pa.shape[1]]
    pad = np.zeros(pa.shape[:2], bool)
    pad[:big.shape[0], :big.shape[1]] = big
    base[pad] = base[pad] * 0.45 + np.array([240.0, 40.0, 40.0]) * 0.55
    return Image.fromarray(base.clip(0, 255).astype("uint8"))


def parts_likeness(a, b):
    """How many of the original's parts (links, buttons, sections and so on) the build has."""
    x, y = Counter(a.get("outline", [])), Counter(b.get("outline", []))
    if not x:
        return None
    return {"similarity": 100 * sum((x & y).values()) / sum(x.values()), "missing": dict((x - y).most_common(6))}


def borrowed(a, b, run=6):
    """Rebuild what it does, not what it owns: the original's name and any run of words the build took as they are."""
    wa, wb = [re.findall(r"\w+", s.lower()) for s in (a.get("text", ""), b.get("text", ""))]
    have = {tuple(wb[i:i + run]) for i in range(len(wb) - run + 1)}
    found, i = [], 0
    while i <= len(wa) - run:
        if tuple(wa[i:i + run]) in have:
            j = i + run
            while j < len(wa) and tuple(wa[j - run + 1:j + 1]) in have:
                j += 1
            found.append(" ".join(wa[i:j]))
            i = j
        else:
            i += 1
    name = " ".join(re.findall(r"\w+", re.split(r"[|\-:–—]", a.get("title", ""))[0].lower()))
    build = " ".join(wb)
    return {"name": name if name and re.search(rf"\b{re.escape(name)}\b", build) else None, "phrases": found[:8]}


# ---------- feature parity (port of replica-skill's parity.py: must 3, should 2, could 1; partial counts half) ----------
WEIGHT = {"must": 3, "should": 2, "could": 1, "p0": 3, "p1": 2, "p2": 1}
CREDIT = {"yes": 1.0, "done": 1.0, "partial": 0.5, "no": 0.0, "": 0.0, "todo": 0.0}


def parity(path, layout_reports=()):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = [(x or "").strip().lower() for x in reader.fieldnames or []]
        for need in ("feature", "priority", "clone"):
            if need not in fields:
                raise ValueError(f"{path} has no '{need}' column. Columns needed: feature, area, priority, original, clone, notes")
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items() if isinstance(v, str)} for r in reader]
    counted, skipped, extras, problems = [], [], [], []
    for n, r in enumerate(rows, 2):
        if not r.get("feature"):
            continue
        clone, prio = r.get("clone", "").lower(), r.get("priority", "").lower()
        if (r.get("original", "yes").lower() or "yes") in ("no", "n", "false"):
            extras.append(r["feature"])
        elif clone == "skip":
            skipped.append(r["feature"])
        else:
            if prio not in WEIGHT:
                problems.append(f"line {n}: priority '{prio}' is not must, should or could, counted as could")
            if clone not in CREDIT:
                problems.append(f"line {n}: clone '{clone}' is not yes, partial, no or skip, counted as no")
            counted.append({**r, "weight": WEIGHT.get(prio, 1), "credit": CREDIT.get(clone, 0.0)})
    total = sum(r["weight"] for r in counted)
    score = 100 * sum(r["weight"] * r["credit"] for r in counted) / total if total else 0.0
    missing = sorted((r for r in counted if r["credit"] < 1), key=lambda r: (-r["weight"], r["credit"], r.get("area", ""), r["feature"]))
    musts = [r for r in counted if r["weight"] == 3]
    done = sum(r["credit"] == 1 for r in musts)
    layouts = [json.loads(Path(p).read_text(encoding="utf-8"))["score"] for p in layout_reports]
    layout = sum(layouts) / len(layouts) if layouts else None
    overall = score * 0.8 + layout * 0.2 if layout is not None else score
    verdict = "not shippable" if done < len(musts) or not counted else "shippable" if score >= 80 else "not shippable"
    return {"score": round(score, 1), "layout": None if layout is None else round(layout, 1), "overall": round(overall, 1), "must_done": done, "must_total": len(musts), "verdict": verdict,
            "missing": [{"feature": r["feature"], "area": r.get("area", ""), "priority": {3: "must", 2: "should", 1: "could"}[r["weight"]], "clone": r.get("clone", "") or "no"} for r in missing],
            "skipped": skipped, "extras": extras, "problems": problems}


# ---------- measure ----------
def _hex(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


def _rgb(path):
    with Image.open(path) as im:
        return im.convert("RGB")


def palette(arr, min_share=0.01, limit=10):
    """Exact colors covering at least min_share of the picture, biggest first."""
    flat = arr.reshape(-1, 3).astype(np.int32)
    packed = (flat[:: max(1, len(flat) // 200000)] * (65536, 256, 1)).sum(axis=1)
    vals, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts)
    total = counts.sum()
    return [{"hex": "#%06x" % vals[i], "share": round(float(counts[i] / total), 3)} for i in order[:limit] if counts[i] / total >= min_share]


def measure(img):
    """Sizes, colors and spacing read from pixels: measuring gets it right where guessing gets close."""
    arr = np.array(img.convert("RGB"))
    h, w, _ = arr.shape
    pal = palette(arr)
    bg = pal[0]["hex"] if pal else _hex(arr[0, 0])
    bgv = np.array([int(bg[i:i + 2], 16) for i in (1, 3, 5)])
    ink = np.abs(arr.astype(int) - bgv).sum(axis=2) > 24
    on = ink.any(axis=1)
    rows, y = [], 0
    while y < h:
        if on[y]:
            e = y
            while e + 1 < h and on[e + 1]:
                e += 1
            xs = np.where(ink[y:e + 1].any(axis=0))[0]
            rows.append({"top": y, "height": e - y + 1, "left": int(xs[0]), "right": int(xs[-1])})
            y = e + 1
        else:
            y += 1
    gaps = [rows[i + 1]["top"] - rows[i]["top"] - rows[i]["height"] for i in range(len(rows) - 1)]
    lefts = Counter(r["left"] for r in rows)
    return {"size": [w, h], "background": bg, "palette": pal, "rows": rows, "gaps": gaps, "left_edge": lefts.most_common(1)[0][0] if lefts else None,
            "common_gap": Counter(gaps).most_common(1)[0][0] if gaps else None}


# ---------- compare ----------
def load_capture(folder):
    folder = Path(folder)
    shots = {int(m[1]): p for p in folder.glob("screenshot-*.png") if (m := re.fullmatch(r"screenshot-(\d+)\.png", p.name))}
    info = json.loads((folder / "capture.json").read_text(encoding="utf-8")) if (folder / "capture.json").exists() else None
    return shots, info


def _b64(im, width=320):
    im = im.convert("RGB")
    im = im.resize((width, max(1, im.height * width // im.width)))
    b = io.BytesIO()
    im.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def compare(orig, build, out, good=GOOD):
    sa, ia = load_capture(orig)
    sb, ib = load_capture(build)
    if not sa:
        raise ValueError(f"no screenshot-<width>.png in {orig}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    todo, widths, cards, blank = [], [], [], False
    for w in sorted(sa, reverse=True):
        a = _rgb(sa[w])
        if w not in sb:
            widths.append({"width": w, "layout": 0.0, "pixel": 0.0})
            todo.append(f"At {w} px: the build has no screenshot. Capture it at this width.")
            continue
        b = _rgb(sb[w])
        arr_a, arr_b = np.array(a), np.array(b)
        d = diff_pictures(arr_a, arr_b)
        s = d["layout"]
        widths.append({"width": w, "layout": round(s, 1), "pixel": round(d["pixel"], 1)})
        if len(palette(arr_b, 0.002)) <= 1 and len(palette(arr_a, 0.002)) > 1:
            blank = True
            todo.append(f"At {w} px: the build is blank. Check that it starts and loads.")
        if abs(d["height_delta_pct"]) > 10:
            todo.append(f"At {w} px: the build's page is {abs(d['height_delta_pct']):.0f}% {'taller' if d['height_delta_pct'] > 0 else 'shorter'} than the original.")
        if s < good:
            todo.append(f"At {w} px: layout {s:.0f}%. The {where_most(d['flags']) or 'whole page'} differs most.")
            ma, mb = measure(a), measure(b)
            if len(ma["rows"]) != len(mb["rows"]):
                todo.append(f"At {w} px: the original has {len(ma['rows'])} rows of content and the build has {len(mb['rows'])}.")
            if ma["common_gap"] is not None and mb["common_gap"] is not None and ma["common_gap"] != mb["common_gap"]:
                todo.append(f"At {w} px: the usual gap between rows is {ma['common_gap']} px in the original and {mb['common_gap']} px in the build.")
        cards.append(f'<section><h2>{w} px <span class="{"ok" if s >= good else "no"}">layout {s:.0f}%</span> <small>exact pixels {d["pixel"]:.0f}%</small></h2><div class="r"><figure><img src="{_b64(a)}"><figcaption>Original</figcaption></figure><figure><img src="{_b64(b)}"><figcaption>Your build</figcaption></figure><figure><img src="{_b64(heat(d))}"><figcaption>Where the layout differs</figcaption></figure></div></section>')
    parts = taken = None
    if ia and ib:
        parts, taken = parts_likeness(ia, ib), borrowed(ia, ib)
        if parts and parts["missing"]:
            todo.append(f"Parts {parts['similarity']:.0f}% there. The original has more of: " + ", ".join(f"{k} ({v})" for k, v in parts["missing"].items()))
        if taken["name"]:
            todo.append(f"Make it yours: the build still says the original's name, \"{taken['name']}\".")
        if taken["phrases"]:
            todo.append("Make it yours: write your own words for " + "; ".join(f'"{p}"' for p in taken["phrases"][:4]) + ".")
    score = sum(w["layout"] for w in widths) / len(widths)
    rep = {"score": round(score, 1), "good_enough": score >= good and not blank, "bar": good, "widths": widths, "parts": parts, "borrowed": taken, "todo": todo}
    (out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    items = "".join(f"<li>{html.escape(t)}</li>" for t in todo) or "<li>Nothing left on the list.</li>"
    extra = f'<div class="s"><b>{parts["similarity"]:.0f}%</b><span>parts there</span></div>' if parts else ""
    (out / "report.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>rebuild-proof report</title><style>
body{{margin:0;background:#101318;color:#e7ebf0;font:15px/1.45 system-ui,Segoe UI,sans-serif;padding:28px;max-width:1100px}} h1{{margin:0 0 14px;font-size:24px}} h2{{font-size:16px;margin:24px 0 10px}} h2 span{{margin-left:8px}} small{{color:#94a0af;font-weight:400;margin-left:8px}}
.ok{{color:#6ee7a0}} .no{{color:#fbbf60}} .g{{display:flex;gap:10px;flex-wrap:wrap}} .s{{background:#191e26;border:1px solid #2b3340;border-radius:8px;padding:10px 18px}} .s b{{font-size:28px;display:block}} .s span{{color:#94a0af;font-size:12px}}
.r{{display:flex;gap:12px;flex-wrap:wrap}} figure{{margin:0;width:320px}} img{{width:100%;border:1px solid #2b3340;border-radius:6px;display:block}} figcaption{{color:#94a0af;font-size:12px;margin-top:4px}} li{{margin:3px 0}}
</style><h1>How close is your build?</h1><div class="g"><div class="s"><b class="{'ok' if rep['good_enough'] else 'no'}">{score:.0f}%</b><span>layout alike, bar is {good:.0f}%. Colors are ignored</span></div>{extra}</div><h2>What to fix next</h2><ul>{items}</ul>{''.join(cards)}""", encoding="utf-8")
    return rep


# ---------- stories ----------
def write_stories(captures, out):
    """A screen index, a backlog with checkable acceptance lines, and a feature matrix to fill in, from what was captured."""
    captures, out = Path(captures), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    folders = sorted({p.parent for p in captures.rglob("screenshot-*.png")})
    index, stories, seen = ["# Screens", ""], ["# Stories", "", "Every acceptance line says how it is checked: [snap] snapshot compared with the original, [unit] test, [manual] a person tries it.", ""], set()
    features = []
    n = 0
    for f in folders:
        _, info = load_capture(f)
        info = info or {}
        name = info.get("title") or f.name
        widths = sorted(int(re.search(r"(\d+)\.png", s.name)[1]) for s in f.glob("screenshot-*.png"))
        index += [f"## {name}", f"- Folder: `{f.relative_to(captures) if f != captures else '.'}`", f"- Widths: {', '.join(map(str, widths))}"]
        if info.get("headings"):
            index.append("- Headings: " + "; ".join(info["headings"][:12]))
        if info.get("actions"):
            index.append("- Actions: " + "; ".join(dict.fromkeys(info["actions"]))[:400])
        index.append("")
        n += 1
        stories += [f"### S-{n:03} See the {name} screen", f"As the user, I open {name} and it is laid out like the original at every width.", "Acceptance:", f"- [snap] `rebuild_proof.py compare` scores {GOOD:.0f}% or more for this screen.", "Status: todo", ""]
        features.append({"feature": f"See the {name} screen", "area": name, "priority": "must", "original": "yes", "clone": "no", "notes": ""})
        for action in dict.fromkeys(info.get("actions", [])):
            if (name, action) in seen:
                continue
            seen.add((name, action))
            n += 1
            stories += [f"### S-{n:03} {action}", f'As the user, on {name}, I use "{action}".', "Acceptance:", "- [manual] Write what should happen, after trying it in the original.", f'- [snap] The "{action}" control shows at all widths.', "Status: todo", ""]
            features.append({"feature": action, "area": name, "priority": "should", "original": "yes", "clone": "no", "notes": ""})
    (out / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    (out / "STORIES.md").write_text("\n".join(stories), encoding="utf-8")
    with open(out / "features.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["feature", "area", "priority", "original", "clone", "notes"])
        w.writeheader()
        w.writerows(features)
    return out


# ---------- demo ----------
def demo(out):
    out = Path(out)
    cap = HERE / "examples" / "captures"
    print("One original, two builds, all made-up pages captured from examples/*.html.\n")
    first = compare(cap / "original", cap / "first-try", out / "first-try")
    print(f"first try: layout {first['score']:.0f}% (bar {GOOD:.0f}%). What to fix:")
    for t in first["todo"][:7]:
        print("  -", t)
    fixed = compare(cap / "original", cap / "fixed", out / "fixed")
    px = sum(w["pixel"] for w in fixed["widths"]) / len(fixed["widths"])
    print(f"\nfixed build, own name, words and colors: layout {fixed['score']:.0f}%, exact pixels {px:.0f}%, {'good enough' if fixed['good_enough'] else 'not there yet'}, {len(fixed['todo'])} left")
    par = parity(HERE / "examples" / "features.csv", [out / "fixed" / "report.json"])
    print(f"features: {par['score']:.0f}%, must-haves {par['must_done']}/{par['must_total']}, overall {par['overall']:.0f}%: {par['verdict']}")
    for m in par["missing"]:
        print(f"  - {m['priority']}: {m['feature']} ({m['clone']})")
    m = measure(_rgb(cap / "original" / "screenshot-1280.png"))
    print(f"\nmeasured from the original at 1280 px: background {m['background']}, {len(m['rows'])} rows, usual gap {m['common_gap']} px, colors " + " ".join(c["hex"] for c in m["palette"][:5]))
    print(f"\nreport: {out / 'first-try' / 'report.html'}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Study an app from the outside, build your own, and prove how close you got.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="screenshots at three widths, plus visible text and page outline")
    c.add_argument("target", help="a URL or a local HTML file")
    c.add_argument("--out", default="capture/original")
    c.add_argument("--widths", default="1280,768,390")
    m = sub.add_parser("measure", help="colors, rows and spacing from a screenshot")
    m.add_argument("image")
    p = sub.add_parser("compare", help="score a build's layout against the original and list what to fix. Exits 1 under the bar")
    p.add_argument("original")
    p.add_argument("build")
    p.add_argument("--out", default="proof")
    p.add_argument("--bar", type=float, default=GOOD)
    q = sub.add_parser("parity", help="feature score and what to build next, from features.csv. Exits 1 if not shippable")
    q.add_argument("features")
    q.add_argument("--layout", nargs="*", default=[], help="report.json files from compare, weighted 20%% in the overall score")
    s = sub.add_parser("stories", help="a screen index, a backlog and a feature matrix from captures")
    s.add_argument("captures")
    s.add_argument("--out", default="docs/screens")
    d = sub.add_parser("demo", help="run on the bundled example, no browser needed")
    d.add_argument("--out", default="proof-demo")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "demo":
            return demo(a.out)
        if a.cmd == "capture":
            shots = capture(a.target, a.out, tuple(int(w) for w in a.widths.split(",")))
            print("\n".join(str(x) for x in shots) + f"\n{Path(a.out) / 'capture.json'}")
        elif a.cmd == "measure":
            print(json.dumps(measure(_rgb(a.image)), indent=1))
        elif a.cmd == "compare":
            r = compare(a.original, a.build, a.out, a.bar)
            print(f"layout {r['score']:.0f}% (bar {a.bar:.0f}%): {', '.join(str(w['width']) + ' px ' + str(round(w['layout'])) + '%' for w in r['widths'])}")
            for t in r["todo"]:
                print("  -", t)
            print(f"report: {Path(a.out) / 'report.html'}")
            return 0 if r["good_enough"] else 1
        elif a.cmd == "parity":
            r = parity(a.features, a.layout)
            print(f"features {r['score']:.0f}%, must-haves {r['must_done']}/{r['must_total']}" + (f", layout {r['layout']:.0f}%, overall {r['overall']:.0f}%" if r["layout"] is not None else "") + f": {r['verdict']}")
            for x in r["missing"]:
                print(f"  - {x['priority']}: {x['feature']} ({x['clone']})" + (f" [{x['area']}]" if x["area"] else ""))
            for x in r["problems"]:
                print("  !", x)
            return 0 if r["verdict"] == "shippable" else 1
        else:
            print(write_stories(a.captures, a.out))
    except (ValueError, RuntimeError, OSError) as e:
        sys.exit(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
