"""Run the existing smoke contract with direct HTTP and redacted progress.

No backend source changes, credentials, persisted config or service operations.
Use this as a task-local harness; the canonical smoke implementation is loaded
from scripts/backend_smoke_check.py unchanged.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cyber_smoke", ROOT / "scripts" / "backend_smoke_check.py")
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def safe_detail(value):
    text = str(value)
    # Never preserve source/redirect URLs or credential-bearing error bodies.
    if re.search(r"\bHTTP \d{3}\b", text):
        return re.search(r"\bHTTP \d{3}\b", text).group(0)
    text = re.sub(r"https?://[^\s\"'<>]+", "[url-redacted]", text, flags=re.I)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(password|secret|authorization|cookie|ticket|api[_-]?token)\s*[:=]\s*[^,;\s]+", r"\1=[redacted]", text)
    return text[:2000]


configured = urllib.request.getproxies()
print(json.dumps({"event": "transport", "proxy_configured": bool(configured), "proxy_schemes": sorted(configured), "mode": "direct"}), flush=True)
urllib.request.getproxies = lambda: {}
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

OriginalCheckSpec = smoke.CheckSpec
recorded = []
started = time.monotonic()


def CheckSpec(name, run):
    def checked_run():
        check_started = time.monotonic()
        print(json.dumps({"event": "start", "check": name}), flush=True)
        try:
            result = run()
            detail = safe_detail(result.detail)
        except Exception as exc:
            detail = safe_detail(exc)
            result = smoke.CheckResult(name, False, detail)
        item = {"name": result.name, "ok": result.ok, "seconds": round(time.monotonic() - check_started, 3), "detail": detail}
        recorded.append(item)
        print(json.dumps({"event": "result", **item}, ensure_ascii=False), flush=True)
        return result
    return OriginalCheckSpec(name, checked_run)


smoke.CheckSpec = CheckSpec
args = smoke.build_parser().parse_args(sys.argv[1:])
# This run deliberately does not authenticate or pull credentials from env.
args.api_token = ""
args.login_username = ""
args.login_password = ""
args.systemd = False
smoke.run_checks(args)
summary = {
    "event": "summary", "mode": "direct", "seconds": round(time.monotonic() - started, 3),
    "count": len(recorded), "passed": sum(item["ok"] for item in recorded),
    "failed": sum(not item["ok"] for item in recorded), "checks": recorded,
}
print(json.dumps(summary, ensure_ascii=False), flush=True)
raise SystemExit(1 if summary["failed"] else 0)
