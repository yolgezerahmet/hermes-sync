#!/usr/bin/env python3
"""sync_web_ui.py — sync_motor Web Paneli (durum + versiyon takibi)
==================================================================
Minimal, bağımlılıksız (stdlib): http.server + sync_motor/rclone.
  GET /                  → panel (per-node: son push, çakışma, versiyon sayısı)
  GET /api/status        → JSON (ajan-okur; agent-status benzeri + versiyonlar)
  GET /api/versions?node → node'un GDrive versiyonları
  POST /api/backup?node  → node için GDrive versiyon yedeği tetikle
Varsayılan bind 127.0.0.1:8147 (Windows'tan SSH tüneli ile erişim).
"""
import json, os, subprocess, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOTOR = "/root/cumulus-sync-motor/sync_motor.py"
COORD = "/root/cumulus-sync-motor/sync_coordinator.py"
HUB = os.environ.get("SYNC_WEB_HUB", "gdrive:cumulusos-backups/versiyonlu")

def _sh(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout, r.stderr
    except Exception as e:
        return False, "", str(e)

import time as _t
_ver_cache = {}
_ver_cache_ts = {}

def node_list():
    """config.json'dan doğrudan oku (banner parse yok)."""
    try:
        cfg = json.load(open("/root/cumulus-sync-motor/config.json"))
        return list(cfg.get("dirs", {}).keys())
    except Exception:
        return []

def versions(node, ttl=60):
    now = _t.time()
    if _ver_cache.get(node) is not None and now - _ver_cache_ts.get(node, 0) < ttl:
        return _ver_cache[node]
    ok, out, _ = _sh(["rclone", "lsf", f"{HUB}/{node}", "--files-only"], timeout=45)
    vs = sorted([f for f in out.splitlines() if f.endswith(".tar.gz")]) if ok else []
    _ver_cache[node] = vs
    _ver_cache_ts[node] = now
    return vs

def last_push_map():
    try:
        p = "/root/.hermes/state/last_push.json"
        return json.load(open(p))
    except Exception:
        return {}

def conflicts():
    ok, out, _ = _sh(["python3", MOTOR, "conflicts"])
    return [l.strip() for l in out.splitlines() if ".conflict" in l]

def versions(node):
    ok, out, _ = _sh(["rclone", "lsf", f"{HUB}/{node}", "--files-only"])
    if not ok:
        return []
    return sorted([f for f in out.splitlines() if f.endswith(".tar.gz")])

def last_run_summary():
    try:
        p = "/root/.hermes/state/sync_last_run.json"
        if not os.path.exists(p):
            return None
        hist = json.load(open(p)).get("history", [])
        return hist[-1] if hist else None
    except Exception:
        return None

def api_status():
    nodes = node_list()
    lp = last_push_map()
    cf = conflicts()
    lr = last_run_summary()
    data = {"nodes": [], "conflicts": len(cf), "conflict_files": cf[:10],
            "son_kosu": lr, "machines": []}
    for n in nodes:
        vs = _ver_cache.get(n, [])   # cache-only — /api/versions tazeler (hız)
        data["nodes"].append({
            "node": n, "last_push": lp.get(n, None),
            "versions": len(vs), "latest": vs[-1] if vs else None,
        })
    # çoklu makine durumu — sync_coordinator çıktısı (hızlı, 8s cap)
    ok, out, _ = _sh(["python3", COORD, "status", "--json"], timeout=8)
    if ok:
        try:
            c = json.loads(out)
            data["machines"] = c.get("machines", [])
        except Exception:
            pass
    rec = []
    if cf:
        rec.append(f"ÇÖZ: {len(cf)} çakışma — sync_motor.py conflicts ile incele")
    if lr and lr.get("rc", 0) != 0:
        rec.append(f"SON KOŞU HATALI: {lr.get('komut')} rc={lr.get('rc')} @ {(lr.get('ts') or '?')[:19]}")
    if not rec:
        rec.append("OK — eylem gerekmiyor")
    data["recommendation"] = " | ".join(rec)
    return data

def html_page(status):
    rows = ""
    for n in status["nodes"]:
        rows += (f"<tr><td>{n['node']}</td><td>{n['last_push'] or '—'}</td>"
                 f"<td>{n['versions']}</td><td>{n['latest'] or '—'}</td></tr>")
    cf = "".join(f"<li>{c}</li>" for c in status["conflict_files"]) or "<li>yok</li>"
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>sync_motor — Durum</title>
<style>body{{font-family:monospace;margin:2em;background:#111;color:#0f0}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #333;padding:6px;text-align:left}}
.ok{{color:#0f0}}.warn{{color:#ff0}}</style></head><body>
<h1>sync_motor · GDrive Versiyon Takibi</h1>
<p>{status['recommendation']}</p>
<h2>Node'lar</h2><table><tr><th>node</th><th>son push</th><th>versiyon</th><th>son versiyon</th></tr>{rows}</table>
<h2>Çakışmalar ({status['conflicts']})</h2><ul>{cf}</ul>
<p><small><a href="/api/status">/api/status JSON</a></small></p>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/status":
            return self._send(200, json.dumps(api_status(), ensure_ascii=False), "application/json")
        if u.path == "/api/versions":
            q = urllib.parse.parse_qs(u.query)
            node = q.get("node", [""])[0]
            vs = versions(node) if node else []
            return self._send(200, json.dumps({"node": node, "versions": vs[-20:]}, ensure_ascii=False), "application/json")
        if u.path == "/":
            return self._send(200, html_page(api_status()))
        return self._send(404, "not found")
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/backup":
            q = urllib.parse.parse_qs(u.query)
            node = q.get("node", [""])[0]
            ok, out, err = _sh(["python3", MOTOR, "backup", "--node", node] if node else
                               ["python3", MOTOR, "backup"], timeout=600)
            return self._send(200, json.dumps({"ok": ok, "out": out[-500:], "err": err[-300:]}, ensure_ascii=False), "application/json")
        return self._send(404, "not found")

def main():
    port = int(os.environ.get("SYNC_WEB_PORT", "8147"))
    host = os.environ.get("SYNC_WEB_HOST", "127.0.0.1")
    print(f"sync_motor web paneli: http://{host}:{port}")
    ThreadingHTTPServer((host, port), H).serve_forever()

if __name__ == "__main__":
    main()
