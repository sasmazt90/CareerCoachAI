# CareerCoachAI (AIApply-benzeri kişisel platform)

Bu proje job intake + çoklu CV upload + OpenAI destekli içerik üretimi + ATS odaklı başvuru + mülakat simülasyonu akışını sağlar.

## Özellikler
- OpenAI API Secret (`/settings`)
- Çoklu CV upload (`.txt/.pdf/.docx/.doc`) ve tüm CV'lerden ortak bilgi havuzu
- Ülke için English multi-select
- Çoklu para birimi (`USD/EUR/GBP/TRY/AED`) ve USD normalize eşleştirme
- ATS keyword odaklı CV + Cover Letter üretimi
- Cover Letter ayrı sayfa (`/cover-letters`)
- Job intake (`/jobs/new`)
- 2 aşamalı mülakat simülasyonu (`/interview`):
  - real-time akustik (audio DSP) analizi: stress/confidence index (.wav upload)
  - Stage 1: HR Manager
  - Stage 2: Unit Manager
  - scoring + recommendation + retry + "YOU GOT THE JOB"

## Kurulum
```bash
cd CareerCoachAI
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
python -m app.main
```

## Kullanım
1. `/settings` OpenAI key
2. `/profile-form` profil + ülke + min maaş + currency
3. `/cvs/upload` birden fazla CV yükle
4. `/jobs/new` ilan ekle
5. `/dashboard` Generate Applications
6. `/cover-letters` cover letter görüntüle
7. `/interview` mülakat simülasyonu (metin + opsiyonel .wav ses yükleyerek DSP analizi)

## Önemli Not
Sistem promptları “facts only / no hallucination” kuralıyla hazırlanmıştır.
Yine de nihai gönderimden önce manuel doğrulama önerilir.

## Test
```bash
pytest -q
```
