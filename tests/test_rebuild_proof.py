import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import rebuild_proof as r

CAP = ROOT / "examples" / "captures"
# python imgdiff.py <original> <build> --json from Jakeschincariol/replica-skill, run on these exact captures
UPSTREAM = {(1280, "first-try"): 35.9, (1280, "fixed"): 79.8, (768, "first-try"): 24.1, (768, "fixed"): 85.5, (390, "first-try"): 18.3, (390, "fixed"): 83.2}


def page(color="#2563eb", bg="#ffffff", rows=(100, 200, 300), w=640, h=480):
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 60], fill=color)
    for y in rows:
        d.rectangle([40, y, w - 40, y + 40], fill="#222222")
    return im


def arr(im):
    return np.array(im.convert("RGB"))


class Layout(unittest.TestCase):
    def test_same_page_is_100_on_both_scores(self):
        d = r.diff_pictures(arr(page()), arr(page()))
        self.assertEqual((d["layout"], d["pixel"]), (100.0, 100.0))

    def test_a_rebrand_keeps_the_layout_and_loses_the_pixels(self):
        d = r.diff_pictures(arr(page("#2563eb")), arr(page("#b91c1c")))
        self.assertGreaterEqual(d["layout"], 95)
        self.assertLess(d["pixel"], 95)

    def test_a_missing_row_shows_in_the_layout_and_says_where(self):
        d = r.diff_pictures(arr(page(rows=(100, 200, 300))), arr(page(rows=(100,))))
        self.assertLess(d["layout"], 80)
        self.assertIn(r.where_most(d["flags"]).split()[0], ("middle", "bottom"))

    def test_empty_margins_do_not_pad_the_score(self):
        a, b = Image.new("RGB", (480, 480), "#fff"), Image.new("RGB", (480, 480), "#fff")
        ImageDraw.Draw(a).rectangle([40, 40, 200, 80], fill="#000")
        d = r.diff_pictures(arr(a), arr(b))
        self.assertLess(d["layout"], 1)
        self.assertGreater(d["pixel"], 90)

    def test_different_sizes_are_scaled_and_the_height_is_reported(self):
        d = r.diff_pictures(arr(page(w=1280, h=960)), arr(page(w=640, h=600)))
        self.assertAlmostEqual(d["height_delta_pct"], 25.0, delta=0.5)

    def test_tiny_pictures_do_not_crash(self):
        self.assertEqual(r.diff_pictures(arr(page(w=8, h=8, rows=())), arr(page(w=8, h=8, rows=())))["pixel"], 100.0)

    def test_matches_the_numbers_from_replica_skills_own_tool(self):
        for (w, build), want in UPSTREAM.items():
            a, b = (arr(Image.open(CAP / f / f"screenshot-{w}.png")) for f in ("original", build))
            self.assertEqual(round(r.diff_pictures(a, b)["layout"], 1), want, (w, build))


class Parts(unittest.TestCase):
    def test_counts_what_the_build_lacks(self):
        p = r.parts_likeness({"outline": ["link", "link", "button", "h1"]}, {"outline": ["link", "h1"]})
        self.assertEqual(p["similarity"], 50)
        self.assertEqual(p["missing"], {"link": 1, "button": 1})

    def test_needs_parts_in_the_original(self):
        self.assertIsNone(r.parts_likeness({"outline": []}, {"outline": ["a"]}))


class Borrowed(unittest.TestCase):
    A = {"title": "Harbor Notes - home", "text": "Harbor Notes keeps a logbook that keeps up with the boat every single day"}

    def test_finds_the_name_and_the_copied_run(self):
        t = r.borrowed(self.A, {"text": "Welcome. A logbook that keeps up with the boat, from Harbor Notes."})
        self.assertEqual(t["name"], "harbor notes")
        self.assertEqual(t["phrases"], ["a logbook that keeps up with the boat"])

    def test_your_own_words_are_clean(self):
        self.assertEqual(r.borrowed(self.A, {"text": "Deckhand writes your passage log for you"}), {"name": None, "phrases": []})

    def test_a_short_shared_phrase_is_fine(self):
        self.assertEqual(r.borrowed(self.A, {"text": "up with the boat"})["phrases"], [])


class DomParse(unittest.TestCase):
    def test_reads_what_a_visitor_sees_and_no_script(self):
        d = r.parse_dom("<html><head><title>T</title><style>x{}</style></head><body><h1>Hi</h1><script>evil()</script><a href=x>Go</a><button>Save <b>note</b></button></body></html>")
        self.assertEqual(d["title"], "T")
        self.assertEqual(d["headings"], ["Hi"])
        self.assertNotIn("evil", d["text"])
        self.assertEqual(d["actions"], ["Go", "Save note"])
        self.assertEqual(d["outline"], ["h1", "link", "button"])


class Measure(unittest.TestCase):
    def test_finds_background_palette_and_rows(self):
        m = r.measure(page())
        self.assertEqual(m["background"], "#ffffff")
        self.assertEqual(m["size"], [640, 480])
        self.assertEqual(len(m["rows"]), 4)
        self.assertEqual(m["rows"][1]["left"], 40)
        self.assertIn("#2563eb", [c["hex"] for c in m["palette"]])

    def test_blank_image_has_no_rows(self):
        m = r.measure(Image.new("RGB", (100, 100), "#fff"))
        self.assertEqual((m["rows"], m["common_gap"]), ([], None))


class Compare(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def cap(self, name, im, info=None, widths=(640,)):
        f = self.d / name
        f.mkdir()
        for w in widths:
            im.save(f / f"screenshot-{w}.png")
        if info:
            (f / "capture.json").write_text(json.dumps(info), encoding="utf-8")
        return f

    def test_matching_build_passes_and_writes_the_report(self):
        rep = r.compare(self.cap("a", page()), self.cap("b", page("#b91c1c")), self.d / "o")
        self.assertTrue(rep["good_enough"], rep)
        self.assertTrue((self.d / "o" / "report.html").exists())
        self.assertEqual(json.loads((self.d / "o" / "report.json").read_text(encoding="utf-8"))["score"], rep["score"])

    def test_missing_width_counts_as_zero_and_goes_on_the_list(self):
        rep = r.compare(self.cap("a", page(), widths=(640, 390)), self.cap("b", page()), self.d / "o")
        self.assertEqual([w["layout"] for w in rep["widths"]], [100.0, 0.0])
        self.assertFalse(rep["good_enough"])
        self.assertTrue(any("390 px" in t and "no screenshot" in t for t in rep["todo"]))

    def test_list_names_region_rows_parts_and_borrowed_words(self):
        info_a = {"title": "Acme", "text": "Acme makes one two three four five six seven", "outline": ["button", "h1"]}
        info_b = {"title": "Mine", "text": "Acme one two three four five six seven", "outline": ["h1"]}
        rep = r.compare(self.cap("a", page(), info_a), self.cap("b", page(rows=(100,)), info_b), self.d / "o")
        text = " | ".join(rep["todo"])
        self.assertIn("differs most", text)
        self.assertIn("rows of content", text)
        self.assertIn("button (1)", text)
        self.assertIn('"acme"', text)
        self.assertIn("one two three four five six seven", text)

    def test_empty_original_is_an_error(self):
        (self.d / "a").mkdir()
        with self.assertRaises(ValueError):
            r.compare(self.d / "a", self.cap("b", page()), self.d / "o")

    def test_blank_build_never_passes(self):
        rep = r.compare(self.cap("a", page()), self.cap("b", Image.new("RGB", (640, 480), "#fff")), self.d / "o", good=0)
        self.assertFalse(rep["good_enough"])
        self.assertTrue(any("blank" in t for t in rep["todo"]))

    def test_a_much_shorter_page_goes_on_the_list(self):
        rep = r.compare(self.cap("a", page()), self.cap("b", page(h=300, rows=(100, 200))), self.d / "o")
        self.assertTrue(any("shorter" in t for t in rep["todo"]))


class Parity(unittest.TestCase):
    def csv(self, text):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        p = d / "f.csv"
        p.write_text(text, encoding="utf-8")
        return p, d

    def test_weights_partial_skip_and_extras_like_replica(self):
        p, _ = self.csv("feature,area,priority,original,clone,notes\nA,x,must,yes,yes,\nB,x,should,yes,partial,\nC,x,could,yes,no,\nD,x,must,yes,skip,licensed\nE,x,must,no,yes,mine\n")
        o = r.parity(p)
        self.assertEqual(o["score"], round(100 * (3 + 1) / 6, 1))
        self.assertEqual(o["skipped"], ["D"])
        self.assertEqual(o["extras"], ["E"])
        self.assertEqual([m["feature"] for m in o["missing"]], ["B", "C"])

    def test_a_missing_must_is_never_shippable(self):
        p, _ = self.csv("feature,priority,clone\nA,must,no\nB,could,yes\n" + "C,could,yes\n" * 20)
        o = r.parity(p)
        self.assertGreaterEqual(o["score"], 80)
        self.assertEqual(o["verdict"], "not shippable")

    def test_all_musts_and_80_is_shippable_and_layout_is_a_fifth(self):
        p, d = self.csv("feature,priority,clone\nA,must,yes\nB,should,yes\n")
        (d / "r.json").write_text('{"score": 50}', encoding="utf-8")
        o = r.parity(p, [d / "r.json"])
        self.assertEqual(o["verdict"], "shippable")
        self.assertEqual(o["overall"], 90.0)

    def test_a_wrong_value_is_reported_and_a_wrong_file_refused(self):
        p, _ = self.csv("feature,priority,clone\nA,urgent,maybe\n")
        self.assertEqual(len(r.parity(p)["problems"]), 2)
        p, _ = self.csv("name,value\na,1\n")
        with self.assertRaises(ValueError):
            r.parity(p)


class Stories(unittest.TestCase):
    def test_each_action_gets_a_story_and_a_feature_row(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "home").mkdir()
        page().save(d / "home" / "screenshot-1280.png")
        (d / "home" / "capture.json").write_text(json.dumps({"title": "Home", "text": "x", "headings": ["Plan a trip"], "outline": [], "actions": ["Save note", "Share", "Save note"]}), encoding="utf-8")
        out = r.write_stories(d, d / "docs")
        s = (out / "STORIES.md").read_text(encoding="utf-8")
        self.assertEqual(s.count("### S-"), 3)
        self.assertIn("[snap]", s)
        self.assertIn("Plan a trip", (out / "INDEX.md").read_text(encoding="utf-8"))
        o = r.parity(out / "features.csv")
        self.assertEqual(o["score"], 0)
        self.assertEqual(o["must_total"], 1)


class Capture(unittest.TestCase):
    def test_refuses_anything_but_web_pages_and_local_html(self):
        for bad in ("ftp://example.com", "javascript:alert(1)", "no-such-file.html"):
            with self.assertRaises(ValueError):
                r.target_url(bad)
        self.assertEqual(r.target_url("https://example.com"), "https://example.com")
        self.assertTrue(r.target_url(str(ROOT / "examples" / "original.html")).startswith("file:"))


class RealCapture(unittest.TestCase):
    def test_a_real_browser_capture_reads_the_page(self):
        try:
            r.find_browser()
        except RuntimeError:
            self.skipTest("no Edge or Chrome here")
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        r.capture(str(ROOT / "examples" / "original.html"), d, widths=(390,))
        self.assertEqual(Image.open(d / "screenshot-390.png").width, 390)
        self.assertIn("Tide tables", json.loads((d / "capture.json").read_text(encoding="utf-8"))["headings"])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "rebuild_proof.py"), *map(str, args)], capture_output=True, text=True, encoding="utf-8", timeout=200)

    def test_demo_shows_the_first_try_failing_and_the_rebrand_passing(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        p = self.run_cli("demo", "--out", d)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("first try", p.stdout)
        self.assertIn("good enough", p.stdout)
        self.assertFalse(json.loads((d / "first-try" / "report.json").read_text(encoding="utf-8"))["good_enough"])

    def test_compare_and_parity_exit_codes(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(self.run_cli("compare", CAP / "original", CAP / "first-try", "--out", d / "a").returncode, 1)
        self.assertEqual(self.run_cli("compare", CAP / "original", CAP / "fixed", "--out", d / "b").returncode, 0)
        self.assertEqual(self.run_cli("parity", ROOT / "examples" / "features.csv").returncode, 0)

    def test_a_clear_message_for_a_folder_with_no_screens(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        p = self.run_cli("compare", d, d, "--out", d / "o")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no screenshot", p.stderr)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
