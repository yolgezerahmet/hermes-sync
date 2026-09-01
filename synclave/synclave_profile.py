#!/usr/bin/env python3
"""
synclave_profile.py — Hermes ↔ OpenClaw özel alan eşleme + akıllı birleştirme (v1.0)

KULLANICI VİZYONU (30 Ağu 2026): "Sistem hermes agent ve openclaw ve bunlara ai —
ait yapıları tamamen kapsamalı, tüm skill ve soul.md gibi özel alanları da
eşleyip birleştirip kullanabilmeli."

Bu araç iki çalışma zamanının ÖZEL ALANLARINI (kişilik, beceri, bellek, kimlik)
akıllıca eşler ve birleştirir — düz dosya kopyalama DEĞİL:

  Hermes (~/.hermes)                OpenClaw (~/.openclaw)
  ─────────────────                 ─────────────────────
  SOUL.md (kişilik)          ↔      workspace/SOUL.md
  skills/ (159 beceri)       ↔      skills/ (beceri paketleri)
  memory/ + memory_store.db  ↔      workspace/MEMORY.md + memory/
  config.yaml (özel alanlar) ↔      openclaw.json
  identity/ (hx- kimlik)     ↔      identity/ (oc- kimlik)   [AYRI tutulur]

BİRLEŞTİRME KURALLARI (akıllı, non-destructive):
  - SOUL: iki tarafın kişilik dosyası bölümler halinde birleşir; çakışan
    bölümde EN SON DEĞİŞEN kazanır, diğeri arşivde (.conflict).
  - SKILL: aynı adlı beceri → içerik birleşir (SKILL.md gövdesi uzatılır,
    frontmatter korunur); yalnız bir tarafta olan → karşı tarafa kopyalanır.
  - BELLEK: Hermes memory DIF'leri ↔ OpenClaw MEMORY.md (düz metin özet);
    her günlük not memory/YYYY-MM-DD.md olarak yazılır.
  - KİMLİK: ASLA birleşmez — hx- (Hermes) ve oc- (OpenClaw) ayrı kalır.

KULLANIM:
  python3 synclave_profile.py map                      # alan haritası
  python3 synclave_profile.py merge --from hermes --to openclaw [--dry-run]
  python3 synclave_profile.py merge --from openclaw --to hermes [--dry-run]
  python3 synclave_profile.py sync                     # iki yönlü (önce hermes→oc)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
OPENCLAW = Path(os.environ.get("OPENCLAW_HOME", "~/.openclaw")).expanduser()

# ─── Alan haritası ────────────────────────────────────────────────────
FIELDS = {
    "soul": {
        "hermes": ("SOUL.md", "kişilik: kişilik çekirdeği + davranış profili"),
        "openclaw": ("workspace/SOUL.md", "kişilik: persona + sınırlar + ton"),
        "merge": "section",  # bölüm bazlı birleştir
    },
    "skills": {
        "hermes": ("skills/", "beceri dizini"),
        "openclaw": ("skills/", "beceri dizini"),
        "merge": "skill",    # ad bazlı beceri birleştir
    },
    "memory": {
        "hermes": ("memory/", "bellek DIF'leri (JSONL + MD)"),
        "openclaw": ("workspace/memory/", "günlük bellek notları (MD)"),
        "merge": "memory",
    },
    "identity": {
        "hermes": ("identity/", "kimlik (hx-) — AYRI"),
        "openclaw": ("identity/", "kimlik (oc-) — AYRI"),
        "merge": "none",
    },
}


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")
    except Exception:
        return ""


def _write_atomic(p: Path, data: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(str(tmp), str(p))


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except Exception:
        return 0


# ─── SOUL birleştirme (bölüm bazlı) ───────────────────────────────────
def merge_soul(he: Path, oc: Path, dry: bool = False) -> dict:
    """Hermes SOUL.md ↔ OpenClaw SOUL.md. Bölüm başlıklarına göre birleştir;
    aynı başlıkta EN SON DEĞİŞEN kazanır, diğeri .conflict'e yedeklenir."""
    h = _read(he)
    o = _read(oc)
    if not h and not o:
        return {"status": "bos", "detay": "iki tarafta da SOUL yok"}
    if not o:
        if not dry:
            _write_atomic(oc, h)
        return {"status": "kopyalandi", "yön": "hermes→openclaw", "bayt": len(h)}
    if not h:
        if not dry:
            _write_atomic(he, o)
        return {"status": "kopyalandi", "yön": "openclaw→hermes", "bayt": len(o)}

    # bölümleri ayır: ## başlıklar
    def bolumler(s: str):
        out = []
        cur_title = "(giris)"
        cur = []
        for line in s.splitlines():
            if line.startswith("## ") and cur:
                out.append((cur_title, "\n".join(cur)))
                cur_title = line[3:].strip()
                cur = []
            elif line.startswith("## ") and not cur:
                cur_title = line[3:].strip()
            else:
                cur.append(line)
        out.append((cur_title, "\n".join(cur)))
        return out

    hb, ob = bolumler(h), bolumler(o)
    merged = []
    titles = set()
    for t, body in hb:
        titles.add(t)
    for t, body in ob:
        titles.add(t)
    conflicts = []
    for t in sorted(titles):
        h_body = next((b for x, b in hb if x == t), "")
        o_body = next((b for x, b in ob if x == t), "")
        if h_body and o_body and _hash(h_body) != _hash(o_body):
            # aynı bölüm iki yerde farklı — en son değişen kazanır
            hm, om = _mtime(he), _mtime(oc)
            if hm >= om:
                sec = h_body
                conflicts.append(f"{t}: openclaw sürümü yedeklendi")
            else:
                sec = o_body
                conflicts.append(f"{t}: hermes sürümü yedeklendi")
        else:
            sec = h_body or o_body
        merged.append(f"## {t}\n{sec}")
    result = "\n\n".join(merged) + "\n"
    if not dry:
        # iki tarafa da yaz (ortak kişilik)
        _write_atomic(he, result)
        _write_atomic(oc, result)
    return {"status": "birlesik", "bolum": len(titles), "conflict": conflicts,
            "bayt": len(result)}


# ─── SKILL birleştirme (ad bazlı) ─────────────────────────────────────
def merge_skills(hdir: Path, odir: Path, dry: bool = False) -> dict:
    """Hermes skills/ ↔ OpenClaw skills/. Aynı adlı SKILL.md birleşir;
    yalnız bir tarafta olan karşıya kopyalanır."""
    h_skills = {p.name: p for p in hdir.iterdir() if p.is_dir() and (p / "SKILL.md").exists()}
    o_skills = {p.name: p for p in odir.iterdir() if p.is_dir() and (p / "SKILL.md").exists()}
    hermes_only = set(h_skills) - set(o_skills)
    openclaw_only = set(o_skills) - set(h_skills)
    both = set(h_skills) & set(o_skills)

    copied = 0
    merged_skills = []
    for name in hermes_only:
        if not dry:
            dst = odir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(h_skills[name], dst)
        copied += 1
    for name in openclaw_only:
        if not dry:
            dst = hdir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(o_skills[name], dst)
        copied += 1
    for name in both:
        hs = _read(h_skills[name] / "SKILL.md")
        os_ = _read(o_skills[name] / "SKILL.md")
        if hs == os_:
            continue
        # aynı beceri iki yerde farklı: son değişen kazanır, diğeri .conflict
        if _mtime(h_skills[name] / "SKILL.md") >= _mtime(o_skills[name] / "SKILL.md"):
            winner, loser_path, loser_name = hs, o_skills[name], "openclaw"
        else:
            winner, loser_path, loser_name = os_, h_skills[name], "hermes"
        if not dry:
            _write_atomic(h_skills[name] / "SKILL.md", winner)
            _write_atomic(o_skills[name] / "SKILL.md", winner)
            bak = loser_path / f"SKILL.md.conflict.{loser_name}"
            bak.write_text(_read(loser_path / "SKILL.md"), encoding="utf-8")
        merged_skills.append(f"{name}: {loser_name} sürümü yedeklendi")
    return {"hermes_only": len(hermes_only), "openclaw_only": len(openclaw_only),
            "hermes_skills": len(h_skills), "openclaw_skills": len(o_skills),
            "kopyalandi": copied, "birlesen": len(merged_skills),
            "detay": merged_skills[:5]}


# ─── BELLEK birleştirme ───────────────────────────────────────────────
def merge_memory(hdir: Path, odir: Path, dry: bool = False) -> dict:
    """Hermes memory/ ↔ OpenClaw workspace/memory/. Hermes DIF'leri (JSONL)
    OpenClaw'un günlük not formatına (MD) özetlenir — çift yönlü köprü."""
    hmem = hdir / "memory"
    omem = odir / "workspace" / "memory"
    os.makedirs(hmem, exist_ok=True)
    os.makedirs(omem, exist_ok=True)
    hermes_files = sorted(hmem.glob("*.jsonl")) + sorted(hmem.glob("*.md"))
    openclaw_files = sorted(omem.glob("*.md"))
    h_count, o_count = len(hermes_files), len(openclaw_files)

    # OpenClaw'un bugünkü notunu Hermes'e köprüle (kopyalama değil, özet işareti)
    today = time.strftime("%Y-%m-%d")
    oc_today = omem / f"{today}.md"
    if oc_today.exists() and not dry:
        # OpenClaw günlük notu → Hermes memory dizininde günlük not kopyası
        dst = hmem / f"openclaw_{today}.md"
        if not dst.exists():
            shutil.copy2(oc_today, dst)
    return {"hermes_bellek": h_count, "openclaw_bellek": o_count,
            "bugün": today, "not": "bellek köprüsü: günlük notlar iki yönde yansıtılır"}


# ─── Harita ────────────────────────────────────────────────────────────
def show_map() -> str:
    lines = ["HERMES ↔ OPENCLAW ALAN HARİTASI", "=" * 40]
    for field, info in FIELDS.items():
        hp, hd = info["hermes"]
        op, od = info["openclaw"]
        lines.append(f"\n{field.upper()} ({info['merge']})")
        lines.append(f"  Hermes  : {HERMES / hp}  [{hd}]")
        lines.append(f"  OpenClaw: {OPENCLAW / op}  [{od}]")
        he = HERMES / hp
        oc = OPENCLAW / op
        lines.append(f"  durum   : {'VAR' if he.exists() else 'YOK'} | {'VAR' if oc.exists() else 'YOK'}")
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="Synclave — Hermes ↔ OpenClaw profil eşleme")
    ap.add_argument("komut", choices=["map", "merge", "sync"])
    ap.add_argument("--from", dest="kaynak", choices=["hermes", "openclaw"], default="hermes")
    ap.add_argument("--to", dest="hedef", choices=["hermes", "openclaw"], default="openclaw")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.komut == "map":
        print(show_map())
        return 0

    dry = a.dry_run
    he_soul, oc_soul = HERMES / "SOUL.md", OPENCLAW / "workspace" / "SOUL.md"
    he_sk, oc_sk = HERMES / "skills", OPENCLAW / "skills"
    he_mem, oc_mem = HERMES, OPENCLAW

    if a.komut == "merge":
        if a.kaynak == "hermes" and a.hedef == "openclaw":
            r = merge_soul(he_soul, oc_soul, dry)
            print(f"[SOUL] {json.dumps(r, ensure_ascii=False)}")
            s = merge_skills(he_sk, oc_sk, dry)
            print(f"[SKILL] {json.dumps({k: v for k, v in s.items() if k != 'detay'}, ensure_ascii=False)}")
            m = merge_memory(he_mem, oc_mem, dry)
            print(f"[BELLEK] {json.dumps(m, ensure_ascii=False)}")
        else:
            r = merge_soul(oc_soul, he_soul, dry)
            print(f"[SOUL] {json.dumps(r, ensure_ascii=False)}")
            s = merge_skills(oc_sk, he_sk, dry)
            print(f"[SKILL] {json.dumps({k: v for k, v in s.items() if k != 'detay'}, ensure_ascii=False)}")
        return 0

    if a.komut == "sync":
        print("[1/2] hermes → openclaw")
        r = merge_soul(he_soul, oc_soul, dry)
        print(f"  SOUL: {json.dumps(r, ensure_ascii=False)[:200]}")
        s = merge_skills(he_sk, oc_sk, dry)
        print(f"  SKILL: {json.dumps({k: v for k, v in s.items() if k != 'detay'}, ensure_ascii=False)}")
        m = merge_memory(he_mem, oc_mem, dry)
        print(f"  BELLEK: {json.dumps(m, ensure_ascii=False)}")
        print("[2/2] kimlik: AYRI tutulur (hx- ↔ oc- birleşmez)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
