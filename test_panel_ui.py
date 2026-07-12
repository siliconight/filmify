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


class _Skip(Exception):
    """Environment can't run the browser test — pytest skips, CLI prints SKIP."""


def _run_checks():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise _Skip("playwright not installed "
                    "(pip install playwright && python -m playwright install chromium)")

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
            raise _Skip(f"chromium can't launch ({exc})")
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

        c = chip_near("Gauge")   # visible in BOTH engines (Look is classic-only)
        if c:
            c.click()
            check("dropdown chip opens the popover", shown())
        pg.mouse.click(5, 5)

        c = chip_near("10-bit")
        if c:
            c.click()
            check("checkbox chip opens the popover", shown())

        # Import drop zone: a browser can't expose a dropped file's PATH, so
        # a dropped file is UPLOADED (bytes -> local server -> temp copy) —
        # it must NOT bounce to the picker. Only an empty drop falls back.
        pg.evaluate("""() => {
          window.__loadCalls = [];
          window.loadPath = (path) => window.__loadCalls.push(path === '' ? 'PICKER' : path);
          window.__xhr = [];
          window.XMLHttpRequest = class {
            constructor(){ this.upload = {}; }
            open(m, u){ window.__xhr.push(u); }
            setRequestHeader(){}
            send(){}
          };
        }""")
        pg.evaluate("""() => {
          const dz = document.getElementById('dropzone');
          const dt = new DataTransfer();
          dt.items.add(new File(['x'],'movie.mp4',{type:'video/mp4'}));
          dz.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true}));
        }""")
        check("dropping a file uploads it (no picker bounce)",
              pg.evaluate("() => window.__xhr.slice()") == ["/upload"]
              and pg.evaluate("() => window.__loadCalls.slice()") == [])
        pg.evaluate("""() => {
          const dz = document.getElementById('dropzone');
          dz.dispatchEvent(new DragEvent('drop',{dataTransfer:new DataTransfer(),bubbles:true}));
        }""")
        check("an empty drop falls back to the picker",
              pg.evaluate("() => window.__loadCalls.slice()") == ["PICKER"])
        pg.evaluate("() => window.__loadCalls = []")
        pg.eval_on_selector("#chooseBtn", "el => el.click()")
        check("Choose button opens the picker once (no double-fire)",
              pg.evaluate("() => window.__loadCalls.slice()") == ["PICKER"])

        # Stateless preset tiles: click = the style's full defaults; user
        # tweaks (ratio, grain, ...) never mutate the preset; re-click
        # restores everything.
        styled = pg.evaluate(
            "() => Object.keys(styles).find(n => styles[n].ratio) || ''")
        check("a ratio-bearing style exists for the test", bool(styled))
        if styled:
            want = pg.evaluate(f"() => String(styles['{styled}'].ratio)")
            pg.evaluate(f"() => applyStyle('{styled}')")
            check("style click applies its ratio",
                  pg.eval_on_selector("#ratio", "el => el.value") == want)
            pg.eval_on_selector(
                "#ratio", "el => { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); }")
            pg.eval_on_selector(
                "#grain", "el => { el.value='19'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
            check("manual tweak deselects the tile",
                  pg.evaluate("() => document.querySelectorAll('.scard.sel').length") == 0)
            pg.evaluate(f"() => applyStyle('{styled}')")
            check("re-clicking the tile restores its ratio",
                  pg.eval_on_selector("#ratio", "el => el.value") == want)
            check("re-clicking the tile restores every default (grain)",
                  pg.eval_on_selector("#grain", "el => el.value")
                  == pg.evaluate(
                      f"() => String((styles['{styled}'].grain ?? DEFAULTS.grain))"))

        # Mid-export guard: while RENDERING, slider changes defer the preview
        # instead of spawning an ffmpeg that fights the export.
        pg.evaluate("() => { RENDERING = true; pendingRefresh = false; }")
        pg.eval_on_selector(
            "#grain", "el => { el.value='5'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
        check("param change during export defers the preview",
              pg.evaluate("() => pendingRefresh === true"))
        check("export-pause message shown",
              "paused" in (pg.eval_on_selector("#status", "el => el.textContent") or ""))
        pg.evaluate("() => { RENDERING = false; pendingRefresh = false; }")

        # Engine: film (photochemical) is the default; classic-only
        # controls hide in film mode and return in classic mode; film
        # styles carry their engine into the tile click.
        check("engine select defaults to film",
              pg.eval_on_selector("#pipeline", "el => el.value") == "photochemical")
        check("film-only controls visible by default",
              pg.eval_on_selector("#filmgrp", "el => el.style.display") != "none")
        check("classic-only slider hidden in film mode",
              pg.eval_on_selector("#leak", "el => el.style.display") == "none")
        check("classic-only checkbox hidden in film mode",
              pg.eval_on_selector("#bw", "el => el.parentElement.style.display") == "none")
        pg.eval_on_selector("#pipeline",
            "el => { el.value='legacy'; el.dispatchEvent(new Event('change',{bubbles:true})); }")
        check("classic engine restores classic controls",
              pg.eval_on_selector("#leak", "el => el.style.display") != "none")
        check("film group hides in classic mode",
              pg.eval_on_selector("#filmgrp", "el => el.style.display") == "none")
        pg.evaluate("() => applyStyle('film')")
        check("film tile sets the film engine",
              pg.eval_on_selector("#pipeline", "el => el.value") == "photochemical"
              and pg.eval_on_selector("#leak", "el => el.style.display") == "none")
        pg.evaluate("() => applyStyle('noir')")
        check("classic tile sets the classic engine",
              pg.eval_on_selector("#pipeline", "el => el.value") == "legacy")
        check("settings() carries the engine",
              pg.evaluate("() => settings().pipeline") == "legacy")
        pg.evaluate("() => applyStyle('film')")

        # Monochrome chrome: the accent must carry no hue (r == g == b) so
        # the UI never biases the eye's read of the footage.
        r_, g_, b_ = pg.evaluate("""() => {
          const c = getComputedStyle(document.querySelector('#renderBtn') ||
                                     document.querySelector('button')).backgroundColor;
          return c.match(/\\d+/g).slice(0,3).map(Number);
        }""")
        check("UI accent is neutral gray (no hue)", r_ == g_ == b_)

        browser.close()

    return fails


def test_panel_ui():
    """pytest entry point — skips cleanly when no browser is available."""
    import pytest
    try:
        fails = _run_checks()
    except _Skip as exc:
        pytest.skip(str(exc))
    assert not fails, "panel UI failures: " + ", ".join(fails)


def main():
    try:
        fails = _run_checks()
    except _Skip as exc:
        print(f"SKIP: {exc}")
        return 0
    print(f"\n{'all green' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
