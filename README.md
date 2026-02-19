# CareerCoachAI

Kişisel kullanım için tasarlanmış otomatik iş başvuru asistanı (yerel sürüm).

## Özellikler
- Aday profili, hedef ülke/pozisyon/maaş filtresi
- CV yükleme ve ilana göre CV uyarlama
- Kişiselleştirilmiş cover letter üretimi
- Başvuru sorularına otomatik yanıt üretimi
- Başvuru geçmişini dashboard'da görüntüleme

## Neden Preview'de "Not Found" görünüyor?
Preview çoğu zaman uygulamanın **kök path'ini (`/`)** açar. Eski sürümde `/` route'u yoktu, bu yüzden `Not Found` görünüyordu.
Bu sürümde `/` için bir ana sayfa eklendi.

## Çalıştırma (adım adım)
1) Proje klasörüne girin:
```bash
cd /workspace/CareerCoachAI
```

2) Sunucuyu başlatın:
```bash
python -m app.main
```

3) Tarayıcıdan açın:
- Ana sayfa: `http://127.0.0.1:8000/`
- Dashboard: `http://127.0.0.1:8000/dashboard`

## API Uç Noktaları
- `POST /profile`
- `POST /cvs`
- `POST /jobs`
- `POST /auto-apply`
- `GET /applications`
- `GET /dashboard`

## Hızlı örnek akış (curl)
Önce profil:
```bash
curl -X POST http://127.0.0.1:8000/profile \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "countries": ["Germany", "Netherlands"],
    "target_positions": ["Data Scientist", "ML Engineer"],
    "minimum_salary_usd": 90000,
    "career_history": "Built predictive models that increased conversion by 23% and reduced churn by 17%."
  }'
```

CV yükle:
```bash
curl -X POST http://127.0.0.1:8000/cvs \
  -H "Content-Type: application/json" \
  -d '{"title":"General DS CV","content":"Python, ML, experimentation."}'
```

İlan ekle:
```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "company":"Acme AI",
    "position":"Data Scientist",
    "country":"Germany",
    "salary_usd":120000,
    "description":"Build recommender systems and run A/B tests.",
    "questions":["Why do you want this role?"],
    "seniority":"senior"
  }'
```

Otomatik başvuru çalıştır:
```bash
curl -X POST http://127.0.0.1:8000/auto-apply -H "Content-Type: application/json" -d '{}'
```

Sonuçları gör:
```bash
curl http://127.0.0.1:8000/applications
```
veya tarayıcıda:
- `http://127.0.0.1:8000/dashboard`

## Test
```bash
pytest -q
```

## Not
Bu sürüm, iş ilanı platformlarına gerçek otomatik gönderim yerine yerel/simüle edilmiş bir başvuru orkestrasyonu sağlar.
