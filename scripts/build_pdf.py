"""Render report/dq_report.md to report/dq_report.pdf.

Markdown -> HTML (python-markdown) -> PDF (headless Chrome or Edge print).
No LaTeX or pandoc needed.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report" / "dq_report.md"
OUT = ROOT / "report" / "dq_report.pdf"

CSS = """
@page { size: A4; margin: 16mm 15mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 9.6pt; line-height: 1.42; color: #1b1b1b; }
h1 { font-size: 17pt; margin: 0 0 6px; }
h2 { font-size: 12.5pt; margin: 16px 0 6px; border-bottom: 1px solid #ddd; padding-bottom: 3px; }
p, li { margin: 4px 0; }
table { border-collapse: collapse; margin: 8px 0; font-size: 9pt; }
th, td { border: 1px solid #d6d6d6; padding: 3px 8px; text-align: left; vertical-align: top; }
th { background: #f3f3f1; }
td:nth-child(n+2) { font-variant-numeric: tabular-nums; }
img { max-width: 100%; display: block; margin: 6px 0 10px; }
code { font-family: Consolas, monospace; font-size: 8.6pt; background: #f4f4f2; padding: 0 3px; }
pre { background: #f4f4f2; padding: 8px; font-size: 8.4pt; white-space: pre-wrap; }
pre code { padding: 0; }
hr { border: 0; border-top: 1px solid #ddd; margin: 10px 0; }
h2, table, img { page-break-inside: avoid; break-inside: avoid; }
"""

BROWSERS = [
    shutil.which("chrome"), shutil.which("msedge"), shutil.which("chromium"), shutil.which("google-chrome"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def main() -> None:
    body = markdown.markdown(REPORT.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
    html = f'<!doctype html><html><head><meta charset="utf-8"><title>Heart attack phenotype and data quality report</title><style>{CSS}</style></head><body>{body}</body></html>'
    browser = next((b for b in BROWSERS if b and Path(b).exists()), None)
    if not browser:
        raise SystemExit("No Chrome/Edge found for PDF printing")
    # the HTML sits next to the markdown so relative figure paths resolve
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=REPORT.parent, delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = Path(f.name)
    try:
        with tempfile.TemporaryDirectory() as profile:
            subprocess.run([browser, "--headless", "--disable-gpu", f"--user-data-dir={profile}",
                            "--no-pdf-header-footer", f"--print-to-pdf={OUT}", tmp.as_uri()],
                           check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(tmp)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
