"""Headless-Chrome layout regression probe (run: python src/test_layout.py).

Loads src/layout_probe.html (window 0 + residual + matrix tab) and asserts the
layout fixes stay fixed: no horizontal scroll, ranking table fits its sidebar,
null rows use one colspan cell, null cells stay striped, checked pill uses the
.on class. Needs Chrome (same binary as the report screenshots); exits non-zero
on any failure.
"""
import functools
import http.server
import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome():
    import os
    env = os.environ.get("CHROME_PATH")
    if env:
        return env
    return shutil.which("chrome") or next((p for p in CHROME_CANDIDATES if Path(p).exists()), None)


def main() -> int:
    chrome = find_chrome()
    if not chrome:
        print("FAIL chrome not found (set CHROME_PATH)")
        return 1
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/src/layout_probe.html" % server.server_address[1]
    try:
        proc = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--window-size=1366,768",
             "--virtual-time-budget=8000", "--dump-dom", url],
            capture_output=True, text=True, timeout=120)
    finally:
        server.shutdown()
    m = re.search(r"<title>(\{.*?\})</title>", proc.stdout)
    if not m:
        print("FAIL probe did not report measurements")
        print(proc.stdout[-500:], proc.stderr[-500:])
        return 1
    r = json.loads(m.group(1))
    checks = [
        ("no horizontal scroll", r["scrollW"] == r["clientW"]),
        ("ranking table fits sidebar", r["tableScrollW"] == r["tableHostW"]),
        ("null row colspan", r["nullColspan"] == "4"),
        ("null cells striped (132)", r["stripes"] == 132),
        ("checked pill .on class", r["pillOn"] is True),
        ("checked pill navy", r["pillBg"] == "rgb(20, 48, 79)"),
    ]
    fail = 0
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
        fail += 0 if ok else 1
    print(json.dumps(r))
    print("%d passed, %d failed" % (len(checks) - fail, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())