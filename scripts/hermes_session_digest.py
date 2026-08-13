#!/usr/bin/env python3
"""hermes_session_digest.py — EŞ-SESYON Özeti Üretici (hermes-sync v1.5)
=====================================================================
Bir Hermes ajanının oturum bilgisini PAYLAŞILABİLİR özete dönüştürür.
Diğer ajan 'hermes-sessions' node'unu çekip özeti okur → o ajanın
durumunu öğrenir (kaldığı yer, kararlar, sıradaki işler).

Çıktı: ~/.hermes/agent-share/sessions/YYYYMMDD_HHMMSS_session.md
"""
import os, sys, re, glob, datetime, subprocess

OUT = os.path.expanduser("~/.hermes/agent-share/sessions")
WORKTREES = [
    "/root/.config/superpowers/worktrees/cumulusos/canonical-full-product-gates",
    "/root/cumulusos",
]

def find_state():
    for wt in WORKTREES:
        p = os.path.join(wt, "PROJECT_STATE.md")
        if os.path.exists(p):
            return wt, p
    return None, None

def find_closeout(wt):
    d = os.path.join(wt, "docs")
    if not os.path.isdir(d):
        return None
    hits = sorted(glob.glob(os.path.join(d, "OTURUM_KAPANIS*.md")),
                  key=os.path.getmtime)
    return hits[-1] if hits else None

def git_head(wt):
    try:
        r = subprocess.run(["git", "-C", wt, "log", "--oneline", "-1"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return "?"

def extract_section(text, heading):
    """PROJECT_STATE gibi md'den bölüm çıkar (ör. '## 3. SIRADAKİ')."""
    out, grab = [], False
    for line in text.splitlines():
        if line.startswith("## ") and heading.lower() in line.lower():
            grab = True
            continue
        if grab and line.startswith("## ") and heading.lower() not in line.lower():
            break
        if grab and line.strip():
            out.append(line)
    return out

def build():
    os.makedirs(OUT, exist_ok=True)
    wt, state = find_state()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT, f"{ts}_session.md")
    lines = [f"# Hermes Ajan Oturum Özeti — {ts}",
             f"makine: {os.uname().nodename}", ""]
    if state:
        st = open(state, encoding="utf-8").read()
        lines.append(f"## PROJECT_STATE ({wt})")
        lines.append(f"HEAD: {git_head(wt)}")
        lines.append("```")
        lines.extend(st.splitlines()[:30])
        lines.append("```")
        # KÖPRÜ: deterministik durum — sıradakiler + kararlar her zaman
        for h in ("SIRADAKİ", "KİLİT KARARLAR"):
            sec = extract_section(st, h)
            if sec:
                lines.append(f"\n## {h} (KÖPRÜ)")
                lines.extend(sec[:20])
    closeout = find_closeout(wt) if wt else None
    if closeout:
        lines.append(f"\n## KAPANIŞ ({os.path.basename(closeout)}) — son 25 satır")
        lines.append("```")
        lines.extend(open(closeout, encoding="utf-8").read().splitlines()[-25:])
        lines.append("```")
    lines.append("\n---\nBu özet hermes-sync 'hermes-sessions' node'u ile paylaşılır;")
    lines.append("diğer ajan çekip bu dosyayı okur (ajan durumu = SIRADAKİ + KARARLAR + KAPANIŞ).")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"ÖZET YAZILDI: {out} ({len(lines)} satır)")

if __name__ == "__main__":
    build()
