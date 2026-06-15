#!/usr/bin/env python3
"""
test_panel_ui.py — real-browser checks for the filmify control panel.

Unlike test_filmify.py (which checks the engine and that the panel *serves*),
this loads the actual panel HTML in a headless browser and clicks things —
the only way to catch interaction bugs like "help chip opens then immediately
closes" that pure code-reading misses.

Requires: pip install playwright && python -m playwright install chromium
If Playwright isn't installed, this exits 0 with a SKIP so it never blocks CI
on environments without a browser.

Run: python3 test_panel_ui.py
"""
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render_page():
    spec = importlib.util.spec_from_file_location("filmify", ROOT / "filmify.py")
    fm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fm)
    page = fm.UI_PAGE
    page = (page.replace("__VERSION__", fm.__version__)
                .replace("__FILENAME__", "test.mp4")
                .replace("__STYLES_JSON__", json.dumps(fm.STYLES)))
    page = re.sub(r"__[A-Z_]+__", "{}", page)
    f = Path(tempfile.gettempdir()) / "filmify_panel_test.html"
    f.write_text(page)
    return f


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright not installed "
              "(pip install playwright && python -m playwright install chromium)")
        return 0

    page_file = render_page()
    fails = []

    def check(name, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails.append(name)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — no browser binary, etc.
            print(f"SKIP: chromium can't launch ({exc})")
            return 0
        pg = browser.new_page()
        pg.goto(f"file://{page_file}")
        pop = pg.query_selector("#helppop")

        def chip_near(text):
            for lab in pg.query_selector_all("#side label"):
                if text.lower() in (lab.inner_text() or "").lower():
                    return lab.query_selector(".hq")
            return None

        def shown():
            return pop.evaluate("e => getComputedStyle(e).display") != "none"

        print("filmify panel UI test\n")
        check("help chips exist", len(pg.query_selector_all(".hq")) > 10)
        check("popover hidden initially", not shown())

        # The bug that shipped twice: slider "?" opens then instantly closes.
        c = chip_near("Grain")
        check("slider has a help chip", c is not None)
        if c:
            c.click()
            check("slider chip opens the popover", shown())
            check("popover shows the right text",
                  "grain" in (pop.inner_text() or "").lower())

        pg.mouse.click(5, 5)
        check("clicking away dismisses", not shown())

        c = chip_near("Look")
        if c:
            c.click()
            check("dropdown chip opens the popover", shown())
        pg.mouse.click(5, 5)

        c = chip_near("10-bit")
        if c:
            c.click()
            check("checkbox chip opens the popover", shown())

        # Import drop zone: a browser can't expose a dropped file's path, so a
        # drop (and a click) must open the picker exactly once — not silently
        # do nothing, not double-fire. (Regression: drop used to read f.path,
        # always undefined, so it fell through confusingly.)
        pg.evaluate("""() => {
          window.__loadCalls = [];
          window.loadPath = (path) => window.__loadCalls.push(path === '' ? 'PICKER' : path);
        }""")
        pg.evaluate("""() => {
          const dz = document.getElementById('dropzone');
          const dt = new DataTransfer();
          dt.items.add(new File(['x'],'movie.mp4',{type:'video/mp4'}));
          dz.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true}));
        }""")
        check("dropping a file opens the picker once",
              pg.evaluate("() => window.__loadCalls.slice()") == ["PICKER"])
        pg.evaluate("() => window.__loadCalls = []")
        pg.eval_on_selector("#chooseBtn", "el => el.click()")
        check("Choose button opens the picker once (no double-fire)",
              pg.evaluate("() => window.__loadCalls.slice()") == ["PICKER"])

        browser.close()

    print(f"\n{'all green' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
