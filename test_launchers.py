#!/usr/bin/env python3
"""
test_launchers.py — static validation for the shell launchers.

The Mac START-HERE launcher once invoked "$PY" filmify.py while never assigning
PY, so double-clicking it did nothing. Neither `bash -n` (valid syntax) nor
shellcheck (PY is uppercase, so it's assumed to be an environment variable and
SC2154 is suppressed) catches that. So the load-bearing guard here is
test_launchers_reference_a_defined_interpreter — the rest is general hygiene.

Run: python3 test_launchers.py   (or: pytest -q test_launchers.py)
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def shell_launchers():
    return sorted(list(ROOT.glob("*.command")) + list(ROOT.glob("*.sh")))


def test_shell_launchers_parse():
    """Every launcher must be syntactically valid bash.

    Line endings are normalized to LF before parsing and the script is fed on
    stdin: these are Unix launchers, and a CRLF checkout on Windows (Git-Bash)
    would otherwise make `bash -n` choke on a stray \\r rather than on any real
    syntax error. .gitattributes keeps the shipped files LF; this makes the
    test robust regardless of how a given machine checked them out."""
    if not shutil.which("bash"):
        import pytest
        pytest.skip("bash not available")
    bad = []
    for f in shell_launchers():
        text = f.read_text().replace("\r\n", "\n").replace("\r", "\n")
        r = subprocess.run(["bash", "-n"], input=text,
                           capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"{f.name}: {r.stderr.strip()}")
    assert not bad, "bash -n failed:\n" + "\n".join(bad)


def test_launchers_reference_a_defined_interpreter():
    """Regression guard for the $PY bug: if a launcher runs "$PY"/"$PYTHON"
    etc., it must actually assign that variable somewhere. Catches the exact
    class of failure that shipped a broken Mac launcher."""
    offenders = []
    for f in shell_launchers():
        text = f.read_text()
        # any interpreter-ish variable that gets *used* as a command
        used = set(re.findall(r'"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?"\s+\S+\.py', text))
        used |= set(re.findall(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?\s+\S+\.py', text))
        for var in used:
            if not re.search(rf'\b{re.escape(var)}=', text):
                offenders.append(f"{f.name}: uses ${var} to run python but never assigns it")
    assert not offenders, "\n".join(offenders)


def test_shell_launchers_shellcheck():
    """General shell hygiene. Skips if shellcheck isn't installed."""
    if not shutil.which("shellcheck"):
        import pytest
        pytest.skip("shellcheck not installed")
    bad = []
    for f in shell_launchers():
        r = subprocess.run(["shellcheck", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"----- {f.name} -----\n{r.stdout.strip()}")
    assert not bad, "shellcheck findings:\n" + "\n".join(bad)


def test_windows_bat_is_ascii():
    """A stray non-ASCII byte can corrupt .bat parsing on some codepages."""
    bad = []
    for bat in ROOT.glob("*.bat"):
        try:
            bat.read_text(encoding="ascii")
        except UnicodeDecodeError:
            bad.append(bat.name)
    assert not bad, "non-ASCII .bat files: " + ", ".join(bad)


def main():
    fails = []
    for name, fn in [
        ("shell launchers parse", test_shell_launchers_parse),
        ("launchers define their interpreter", test_launchers_reference_a_defined_interpreter),
        ("shellcheck clean", test_shell_launchers_shellcheck),
        (".bat files are ASCII", test_windows_bat_is_ascii),
    ]:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as exc:
            print(f"  [FAIL] {name}\n{exc}")
            fails.append(name)
        except Exception as exc:  # e.g. pytest.skip when run as a script
            print(f"  [SKIP] {name} -> {exc}")
    print(f"\n{'all green' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
