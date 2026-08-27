# Türkçe Dil/Yazım Araçları — 2026 ARAŞTIRMA RAPORU (27 Ağu 2026)

## MEVCUT DURUM (bizde kurulu)
```
✅ Vale 3.14.2 + 4 CumulusTR kural seti (yasak-kelimeler/pasif-cati/cumle-uzunlugu/paragraf)
✅ textlint 15.7.1 (TR eklentileri eksik)
✅ TurkicNLP 0.3.0
✅ tr_quality_check v2.2 (48 AI kalıbı, 13 metrik + Zemberek)
✅ tr_sloptrim.py (15 regex, 0-100 puan)
✅ BGE-M3-TR embedding (semantik)
```

## YENİ ARAÇLAR (2026 — değerlendirme)

### 🥇 VNLP (Python) — EN GÜÇLÜ ADAY
```
✅ State-of-the-art hafif Türkçe NLP (morfoloji, POS, spell-check)
✅ Python native (Zemberek Java değil!)
✅ pip install vnlp — kolay entegrasyon
🎯 Morfoloji + yazım denetimi için Zemberek'e modern alternatif
⚠️ Dil modeli boyutu kontrol edilmeli
```

### 🥈 TurkicNLP GÜNCEL (bizde 0.3.0 var — yeni sürüm kontrol)
```
✅ arXiv 2602.19174 — 24 Türk dili tek pipeline
✅ Tokenization + morfoloji + POS + dependency + NER + MT
🎯 Bizde 0.3.0 kurulu — GÜNCELLEME kontrolü şart
```

### 🥉 Zeyrek (Python Zemberek morfoloji)
```
✅ Python implementasyonu (JPype gerekmez)
✅ Lemmatization + morfolojik analiz
🎯 TurkicNLP ile birlikte güçlü morfoloji katmanı
```

### 4. Starlang Tools (Python)
```
✅ Morfoloji + Spell Check + Dependency + Deasciifier + NER
✅ Kapsamlı (Zemberek alternatifi tam paket)
```

### 5. LanguageTool (Java — gramer motoru)
```
✅ 30+ dil, AI destekli gramer + noktalama
⚠️ Türkçe desteği: "cannot yet select Turkish" (forum) — ESKİ versiyonda var
⚠️ Java + 500MB klon — ağır; API server gerekir
🎯 Türkçe kural seti port edilebilir (eski LT sürümünden)
```

### 6. Vale 2026 (zaten var — geliştirme)
```
✅ Vale 5.6K★ MIT — vale.sh "lint prose like code"
✅ YAML kurallar (plagin derleme yok)
🎯 CumulusTR kurallarını genişlet (AI writing kuralları CNCF)
```

### 7. Fixy-TR (duygu + yazım düzeltme)
```
✅ Emotion + spelling düzeltme kuralları
⚠️ Niş — gramerden çok duygu analizi
```

## BİZİM İÇİN EN DEĞERLİ 3
```
🎯 1. VNLP: Python native morfoloji + spell-check (Zemberek Java yükü yok)
🎯 2. TurkicNLP güncellemesi: 0.3.0 → en son (24 dil, NER, MT)
🎯 3. Vale kural genişletme: AI writing kuralları + CNCF desenleri
```

## ÖNERİ (uygulama planı)
```
1. VNLP kur + test: pip install vnlp → Türkçe spell-check + morfoloji
   → tr_quality_check'e VNLP katmanı ekle
2. TurkicNLP güncelle: pip install -U TurkicNLP (en son sürüm)
3. Vale: AI-writing kural seti ekle (CNCF "Signs of AI writing")
4. LanguageTool TR: DEĞERLENDİRME — Java ağırlığı, ancak gramer için
   güçlü; eski TR kuralları port edilebilir (gerekirse)
```

## KAYNAKLAR
```
- github.com/agmmnn/turkish-nlp-resources (kapsamlı liste)
- github.com/yusufusta/awesome-turkish-nlp (küratörlü)
- VNLP: pip vnlp · TurkicNLP: arXiv 2602.19174
- LanguageTool: languagetool.org (Türkçe eski sürümde)
- Vale: vale.sh (5.6K★, MIT)
- Zeyrek: github.com/cnosmn/Turkish-NLP-Lemmatization
- Starlang: github.com/starlangsoftware
```
