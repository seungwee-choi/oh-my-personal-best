#!/usr/bin/env python3
"""export_report.py — render the HTML analysis report to a static PDF or PNG.

Centralizes the headless-browser plumbing so every surface (chat bots, web) gets a
clean static artifact without re-implementing it. Best-effort: locates a
Chrome/Chromium/Edge binary; PDF uses ``--print-to-pdf`` (the template now prints
cleanly), PNG a full-page screenshot (trimmed if ``sips``/ImageMagick is available).
Prints the output path; exits non-zero with a clear message if no browser is found.

Usage:
  python3 export_report.py [--home DIR] [--lang en|ko] [--fmt pdf|png] [--out PATH] [--html PATH]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date

from ompb_env import resolve_home, resolve_lang

# Common install locations + anything on PATH.
_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    shutil.which("google-chrome"),
    shutil.which("google-chrome-stable"),
    shutil.which("chromium"),
    shutil.which("chromium-browser"),
    shutil.which("chrome"),
    shutil.which("microsoft-edge"),
]


def find_browser():
    for c in _CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def _build_html(home, lang):
    """Render the report HTML via build_report.py (no logic duplication)."""
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(tempfile.mkdtemp(prefix="ompb-report-"), "report.html")
    env = dict(os.environ, OMPB_NO_CTA="1")
    subprocess.run([sys.executable, os.path.join(here, "build_report.py"),
                    "--home", home, "--lang", lang, "--out", out],
                   check=True, capture_output=True, env=env, timeout=120)
    return out


def _trim(png):
    """Trim surrounding whitespace if a trimmer is available (optional)."""
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        subprocess.run([magick, png, "-trim", "+repage", png], capture_output=True)


def to_pdf(html_path, out, browser):
    subprocess.run([browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out}", f"file://{html_path}"],
                   check=True, capture_output=True, timeout=120)
    return out


def to_png(html_path, out, browser, width=1240, height=20000):
    subprocess.run([browser, "--headless", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={width},{height}", "--force-device-scale-factor=2",
                    f"--screenshot={out}", f"file://{html_path}"],
                   check=True, capture_output=True, timeout=120)
    _trim(out)
    return out


def export_report(home=None, fmt="pdf", lang=None, out=None, html=None):
    """Render the report to a static artifact. Returns the output path."""
    home = resolve_home(home)
    lang = resolve_lang(lang, home)
    browser = find_browser()
    if not browser:
        raise RuntimeError("no Chrome/Chromium/Edge found — install one to export PDF/PNG "
                           "(the HTML report still works in any browser).")
    html_path = os.path.abspath(html) if html else _build_html(home, lang)
    if out is None:
        out_dir = os.path.join(home, "reports")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"report-{date.today().isoformat()}.{fmt}")
    if fmt == "pdf":
        return to_pdf(html_path, out, browser)
    if fmt == "png":
        return to_png(html_path, out, browser)
    raise ValueError(f"unsupported fmt: {fmt!r} (use 'pdf' or 'png')")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the OMPB analysis report to PDF or PNG.")
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--lang", choices=["en", "ko"], help="Language (default: config.json, else en).")
    ap.add_argument("--fmt", choices=["pdf", "png"], default="pdf")
    ap.add_argument("--out", help="Output path (default: <home>/reports/report-<date>.<fmt>).")
    ap.add_argument("--html", help="Existing report HTML to render (skips the build step).")
    args = ap.parse_args(argv)
    try:
        path = export_report(home=args.home, fmt=args.fmt, lang=args.lang, out=args.out, html=args.html)
    except (RuntimeError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"error: browser export failed: {e}\n")
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
