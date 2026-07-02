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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def shell_launchers():
    return sorted(list(ROOT.glob("*.command")) + list(ROOT.glob("*.sh")))


def _bash_can_lint(bash, timeout=15):
    """True if this bash can parse a trivially valid script."""
    try:
        p = subprocess.run([bash, "-n"], input=b"echo hi\n",
                           capture_output=True, timeout=timeout)
        return p.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _find_lint_bash():
    """Return a bash that can actually lint, or None.

    shutil.which('bash') on Windows commonly resolves to
    C:\\Windows\\System32\\bash.exe -- the WSL launcher. With no distro
    installed that exits nonzero with its message on *stdout* (empty stderr,
    exactly the CI failure we saw) no matter the input, so it can't lint
    anything. Git-Bash is present wherever git is, so fall back to it: probe
    each candidate and return the first that can parse a trivial script.
    """
    cands = []
    w = shutil.which("bash")
    if w:
        cands.append(w)
    git = shutil.which("git")
    roots = []
    if git:
        roots.append(os.path.dirname(os.path.dirname(os.path.realpath(git))))
    roots += [r"C:\Program Files\Git", r"C:\Program Files (x86)\Git"]
    for root in roots:
        cands.append(os.path.join(root, "bin", "bash.exe"))
        cands.append(os.path.join(root, "usr", "bin", "bash.exe"))
    seen = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        if c != w and not os.path.isfile(c):  # which() result is already resolved
            continue
        if _bash_can_lint(c):
            return c
    return None


def test_shell_launchers_parse():
    """Every launcher must be syntactically valid bash.

    Finds a bash that can actually lint. On Windows `shutil.which("bash")`
    usually resolves to the WSL stub, which can't lint anything, so we fall back
    to Git-Bash (present wherever git is). Launchers are read as raw bytes and
    normalized to LF on bytes: they contain UTF-8 (em dash, ellipsis), so
    f.read_text() would mangle them under cp1252 on Windows, and feeding bytes
    also avoids text=True re-inserting CRLF on the write side. If no bash on the
    runner can lint, we skip -- macOS and Linux provide the real coverage.
    """
    bash = _find_lint_bash()
    print(f"[launchers] lint bash = {bash}")  # surfaces in `pytest -s` CI logs
    if bash is None:
        import pytest
        pytest.skip("no bash on this runner can lint a trivial script "
                    "(e.g. only the WSL stub is present); shell-syntax coverage "
                    "runs on the macOS and Linux jobs")
    bad = []
    for f in shell_launchers():
        data = f.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        try:
            r = subprocess.run([bash, "-n"], input=data,
                               capture_output=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError) as e:
            bad.append(f"{f.name}: {e!r}")
            continue
        if r.returncode != 0:
            bad.append(f"{f.name}: {r.stderr.decode('utf-8', 'replace').strip()}")
    assert not bad, "bash -n failed:\n" + "\n".join(bad)


def test_launchers_reference_a_defined_interpreter():
    """Regression guard for the $PY bug: if a launcher runs "$PY"/"$PYTHON"
    etc., it must actually assign that variable somewhere. Catches the exact
    class of failure that shipped a broken Mac launcher."""
    offenders = []
    for f in shell_launchers():
        text = f.read_text(encoding="utf-8")
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
