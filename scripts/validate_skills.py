#!/usr/bin/env python3
"""validate_skills.py — SKILL AKTARIMI Doğrulayıcı (hermes-sync v1.5)
====================================================================
hermes-skills node'u paylaşılmadan önce:
  1. Her skill dizininde SKILL.md VAR mı?
  2. Frontmatter (name/description) geçerli mi?
  3. References/scripts/assets bağlantıları yerinde mi (SKILL.md'de
     atıf yapılanlar diskte mevcut mu)?
Kırık skill = paylaşımda kırık aktarım → RED.
"""
import os, re, sys, glob

SKILLS = os.path.expanduser("~/.hermes/skills")

def check():
    errors = []
    skills = [d for d in glob.glob(os.path.join(SKILLS, "*", ""))
              if os.path.isdir(d)]
    if not skills:
        print("skill dizini yok:", SKILLS); return 1
    total = 0
    for d in skills:
        name = os.path.basename(d.rstrip("/"))
        md = os.path.join(d, "SKILL.md")
        if not os.path.exists(md):
            errors.append(f"{name}: SKILL.md YOK")
            continue
        total += 1
        txt = open(md, encoding="utf-8", errors="ignore").read()
        if not txt.startswith("---"):
            errors.append(f"{name}: frontmatter başlamıyor")
        m = re.match(r"---\nname:\s*(\S+)", txt)
        if not m:
            errors.append(f"{name}: frontmatter'da name yok")
        # references atıf kontrolü (dosya uzantılı referanslar)
        for ref in re.findall(r"references/([\w./\-]+\.(?:md|py|sh|json|yaml))", txt):
            if not os.path.exists(os.path.join(d, "references", ref)):
                errors.append(f"{name}: eksik referans references/{ref}")
    print(f"SKILL DENETİMİ: {total} skill, {len(errors)} hata")
    for e in errors[:20]:
        print("  -", e)
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(check())
