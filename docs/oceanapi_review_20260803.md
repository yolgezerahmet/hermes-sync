# OceanAPI Denetim Raporu — sync_motor.py

Tarih: 2026-08-03 | Model: gpt-5-6-sol | Reasoning: default

**KRİTİK**

- `detect_changes()` ~345-356 ~ Tarama filtresine takılan, geçici olarak okunamayan veya boyut limiti aşan dosyalar manifestte yoksa `deleted` kabul ediliyor; devamındaki push silme yayıyorsa gerçek dosya kaybı oluşur ~ Tarama hatasını, kapsam dışı dosyayı ve gerçek silmeyi ayrı durumlar olarak tutun; silme için açık tombstone/onay kullanın.
- `run_cmd()` ~370-380, `gh_ensure_repo()` ~385 ~ `shell=True` ve yapılandırmadan gelen `repo` değeri komut enjeksiyonuna açık ~ `subprocess.run([...], shell=False)` kullanın; pipe işlemini Python ile yönetin.

**ÖNEMLİ**

- `gh_ensure_repo()` ~385 ~ `gh repo view ... | head -2` pipeline’ında dönüş kodu `head` komutuna aittir; `gh` başarısız olsa bile çoğu durumda `rc == 0` görülebilir ~ Komutu pipesız çalıştırın veya `bash -o pipefail` kullanın; asıl `gh` dönüş kodunu kontrol edin.
- `scan_directory()` ~270-290 ~ `paths` içindeki aynı göreli yollar tek anahtarda birleşiyor; sonraki kök öncekinin envanter kaydını sessizce eziyor. `kernel` yapılandırması bu riski doğrudan taşıyor ~ Anahtara kök kimliği ekleyin veya çakışmayı hata olarak raporlayın.
- `scan_directory()` ~255-270 ~ Gizli dosya kontrolü yalnızca dosya adına uygulanıyor; `secrets/`, `credentials/` gibi hassas dizinlerin içeriği `exclude_dirs` içinde değilse taranabilir ~ Hassas dizinleri yol bileşenleri üzerinden de reddedin.

**İYİLEŞTİRME**

- `load_config()` ~175-190 ~ Geçersiz yapılandırma tipleri doğrulanmadan kullanılıyor; bozuk değerler çalışma sırasında hata üretebilir ~ Şema ve tip doğrulaması ekleyin.
- `save_manifest()` ~330-338 ~ `os.replace()` atomik olsa da `fsync` yok; elektrik kesintisinde son manifest kaybolabilir ~ Dosyayı ve ilgili dizini `fsync` edin.