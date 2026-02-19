# CareerCoachAI (AIApply-benzeri kişisel platform)

Bu proje, kişisel kullanım için job intake + CV upload + OpenAI destekli içerik üretimi + başvuru takip dashboard akışını tek platformda çalıştırır.

## Özellikler
- Web arayüzünden profil yönetimi
- OpenAI API Secret girme alanı (`/settings`)
- CV dosyası upload etme (`/cvs/upload`)
- İş ilanı ekleme (`/jobs/new`)
- Otomatik eşleşme (ülke, pozisyon, minimum maaş)
- OpenAI ile role-specific:
  - Tailored CV metni
  - Cover letter
  - Başvuru sorularına yanıt
- Dashboard üzerinden tüm başvuru kayıtlarını görüntüleme

## Kurulum
```bash
cd CareerCoachAI
python -m app.main
```

## Kullanım
1. `http://127.0.0.1:8000/settings` → OpenAI API key kaydet.
2. `http://127.0.0.1:8000/profile-form` → aday profilini doldur.
3. `http://127.0.0.1:8000/cvs/upload` → CV yükle.
4. `http://127.0.0.1:8000/jobs/new` → ilanları ekle.
5. `http://127.0.0.1:8000/dashboard` → **Generate Applications** ile otomatik üretimi çalıştır.

> Not: OpenAI key girilmezse fallback şablon üretimi kullanılır.

## JSON API uçları
- `POST /profile`
- `POST /cvs`
- `POST /jobs`
- `POST /auto-apply`
- `GET /applications`

## Test
```bash
pytest -q
```
