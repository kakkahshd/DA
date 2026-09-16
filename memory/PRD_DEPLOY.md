# PRD — Skrip Deploy VPS untuk DAHOST

## Problem statement (asli)
Buat skrip deploy sekali jalan untuk repo https://github.com/pandeyoga/DAHOST, mencontoh pola
https://github.com/pandeyoga/dadada (folder `deploy/`). Env tidak boleh mengandung emergent lib.
Domain `dafashionerp.cloud`, IP VPS `187.77.116.148`, Ubuntu 26.04 LTS, SSL auto-renew dengan
email `pk.yogaswastika@gmail.com`. Tidak perlu dijalankan/diverifikasi — hanya buat skrip + perintah terminal VPS.

## Pilihan user
Repo publik · MongoDB lokal di VPS (container) · tidak ada API key tambahan.

## Deliverable (2026-06)
- `/app/deploy/install_vps.sh` — skrip mandiri: clone repo → tulis Dockerfile.backend/frontend,
  docker-compose.yml, Caddyfile, nginx conf, stub `emergentintegrations`, update.sh, backup.sh →
  .env (JWT_SECRET acak, tanpa var Emergent) → build → up → tunggu health & HTTPS → cron backup.
- `/app/deploy/README_DEPLOY.md` — perintah terminal VPS + catatan operasional.

## Temuan penting di repo DAHOST
- `requirements.txt` berisi `emergentintegrations` & `litellm` (URL internal Emergent) → difilter di Dockerfile.
- `backend/routes/marketing_ai_content_tools.py` import `emergentintegrations` level modul → di-stub.
- `frontend/package.json` devDependency `@emergentbase/visual-edits` (aset Emergent) → dihapus saat build.
- Tidak ada `yarn.lock` di repo → `yarn install` tanpa frozen lockfile.
- Upload di `/app/uploads`, backup di `/app/backups`, skrip backup di `/app/scripts` → volume + COPY scripts/.
- Admin di-seed otomatis: admin@garment.com / Admin@123.

## Status
Belum diverifikasi di VPS (sesuai permintaan user). Sintaks bash, YAML compose, dan stub Python sudah dicek lokal.

## Backlog
- P1: jalankan di VPS, kirim log bila build gagal.
- P2: commit folder `deploy/` ke repo DAHOST agar `update.sh` ikut ter-version.
