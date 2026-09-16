"""Regression tests for Iteration 209 — object_storage LOKAL fallback + notif dedup.

Bug utama: unggah CSV iklan Shopee ditolak dengan pesan
'Penyimpanan berkas tidak tersedia: EMERGENT_LLM_KEY belum diset'.
Fix: backend/object_storage.py sekarang default LOCAL (FILE_STORAGE!=object)."""

import io
import os
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dahost-staging.preview.emergentagent.com").rstrip("/")
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@garment.com", "password": "Admin@123"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Shopee CPC CSV sample: metadata rows + header + 2 data rows ────────────
def _shopee_cpc_csv() -> bytes:
    lines = [
        "Username,dagrosirfashion",
        "Nama Toko,Shopee GHS",
        "Periode,2026-08-07 - 2026-08-13",
        "",
        "Nama Iklan,Status,Produk,Dilihat,Jumlah Klik,Biaya,Omzet Penjualan,Konversi,Penjualan Langsung GMV Langsung,Konversi Langsung,Produk Terjual",
        "Iklan Otomatis A,Aktif,Kaos Basic,1200,45,374074,1250000,3,900000,2,5",
        "Iklan Otomatis B,Aktif,Celana Kargo,800,20,120000,500000,1,500000,1,2",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# ── 1. Upload → 200, tersimpan lokal ───────────────────────────────────────
class TestMarketingImportUploadLocal:
    session_id = None

    def test_upload_shopee_ads_csv_local_storage(self, headers):
        # Ambil akun Shopee GHS
        r = requests.get(f"{BASE_URL}/api/marketing/data-import/context-options",
                         params={"source_type": "shopee_ads_cpc"}, headers=headers, timeout=30)
        assert r.status_code == 200
        accs = [a for a in r.json()["accounts"] if a["platform"] == "shopee"]
        assert accs, "tidak ada akun Shopee"
        account_id = accs[0]["id"]

        files = {"file": ("shopee_cpc_test.csv", io.BytesIO(_shopee_cpc_csv()), "text/csv")}
        data = {"source_type": "shopee_ads_cpc", "account_id": account_id}
        r = requests.post(f"{BASE_URL}/api/marketing/data-import/upload",
                          headers=headers, files=files, data=data, timeout=60)

        # HARUS TIDAK ADA pesan "Penyimpanan berkas tidak tersedia"
        assert "Penyimpanan berkas tidak tersedia" not in r.text, r.text
        assert "EMERGENT_LLM_KEY" not in r.text, r.text

        assert r.status_code == 200, r.text
        js = r.json()
        assert js.get("ok") is True
        sid = js.get("session_id") or (js.get("session") or {}).get("id")
        assert sid, js
        TestMarketingImportUploadLocal.session_id = sid

        # Berkas lokal ada di /app/uploads/marketing-data-import/<sid>.csv
        p = UPLOAD_ROOT / "marketing-data-import" / f"{sid}.csv"
        assert p.exists(), f"berkas lokal tidak ada: {p}"
        assert p.stat().st_size > 0

    def test_preview_session_ok(self, headers):
        sid = TestMarketingImportUploadLocal.session_id
        assert sid
        r = requests.get(f"{BASE_URL}/api/marketing/data-import/sessions/{sid}",
                         headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        js = r.json()
        # Mapping / headers muncul
        assert "session" in js or "headers" in js or "mapping" in js, js

    def test_cleanup_delete_session(self, headers):
        sid = TestMarketingImportUploadLocal.session_id
        if not sid:
            pytest.skip("no session")
        r = requests.delete(f"{BASE_URL}/api/marketing/data-import/sessions/{sid}",
                            headers=headers, timeout=30)
        assert r.status_code in (200, 204), r.text
        # Bersihkan berkas lokal jika masih ada
        p = UPLOAD_ROOT / "marketing-data-import" / f"{sid}.csv"
        if p.exists():
            p.unlink()


# ── 2. Grep sanity: put_object jatuh ke lokal tanpa EMERGENT_LLM_KEY ───────
class TestObjectStorageLocalFallback:
    def test_default_mode_is_local(self):
        # Tidak ada FILE_STORAGE=object di env → mode lokal
        assert os.environ.get("FILE_STORAGE", "").lower() != "object"

    def test_put_object_writes_locally(self, tmp_path, monkeypatch):
        # unit test langsung ke fungsi
        import sys
        sys.path.insert(0, "/app/backend")
        from object_storage import put_object, get_object

        payload = b"HELLO-LOCAL-STORAGE-TEST"
        rel = "tests/it209_probe.bin"
        out = put_object(rel, payload, "application/octet-stream")
        assert out["storage"] == "local"
        assert out["url"] == f"/api/uploads/{rel}"
        data, ctype = get_object(rel)
        assert data == payload
        # cleanup
        Path("/app/uploads") / rel
        p = Path("/app/uploads") / rel
        if p.exists():
            p.unlink()


# ── 3. Static /api/uploads route ───────────────────────────────────────────
class TestUploadsRoute:
    def test_missing_upload_returns_404(self):
        r = requests.get(f"{BASE_URL}/api/uploads/nonexistent/does-not-exist-xyz.png", timeout=15)
        assert r.status_code == 404, r.status_code


# ── 4. Notifikasi/regresi ──────────────────────────────────────────────────
class TestNotificationsAndRegression:
    def test_trial_balance_regression(self, headers):
        r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/trial-balance",
                         headers=headers, timeout=30)
        assert r.status_code == 200, r.text

    def test_notifications_not_flooded(self, headers):
        # Endpoint boleh salah satu variasi
        for path in ("/api/rahaza/notifications", "/api/notifications"):
            r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=30)
            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else (data.get("items") or data.get("notifications") or [])
                assert len(items) < 500, f"masih banjir notifikasi: {len(items)}"
                # cek tidak ada 2000+ low_stock
                low = [i for i in items if (i.get("type") == "low_stock" or i.get("dedup_key", "").startswith("low_stock"))]
                assert len(low) <= 50, f"low_stock notif tidak dedup: {len(low)}"
                return
        pytest.skip("notifications endpoint tidak ditemukan")


# ── 5. Catalog image upload via put_object (opsional smoke) ────────────────
class TestCatalogImageUpload:
    def test_upload_png_local(self, headers):
        # PNG 1x1 minimal
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
               b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
               b"\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82")
        # Ambil satu catalog item
        r = requests.get(f"{BASE_URL}/api/marketing/catalog-items", headers=headers, timeout=30)
        if r.status_code != 200:
            pytest.skip(f"catalog-items endpoint: {r.status_code}")
        items = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
        if not items:
            pytest.skip("tidak ada catalog item")
        cid = items[0]["id"]
        original_image = items[0].get("image_url") or items[0].get("image") or ""

        files = {"file": ("probe.png", io.BytesIO(png), "image/png")}
        r = requests.post(f"{BASE_URL}/api/marketing/catalog-items/{cid}/image",
                          headers=headers, files=files, timeout=30)
        if r.status_code == 404:
            pytest.skip("endpoint upload gambar katalog tidak ada")
        assert r.status_code == 200, r.text
        assert "Penyimpanan berkas tidak tersedia" not in r.text
        js = r.json()
        url = js.get("url") or js.get("image_url") or (js.get("item") or {}).get("image_url")
        assert url and url.startswith("/api/uploads/"), js

        # GET url → 200 image
        r2 = requests.get(f"{BASE_URL}{url}", headers=headers, timeout=30)
        assert r2.status_code == 200
        assert "image" in r2.headers.get("Content-Type", "")

        # Pulihkan field gambar
        try:
            requests.patch(f"{BASE_URL}/api/marketing/catalog-items/{cid}",
                           headers=headers, json={"image_url": original_image}, timeout=15)
        except Exception:
            pass
        # Hapus file lokal probe
        rel = url.replace("/api/uploads/", "")
        p = UPLOAD_ROOT / rel
        if p.exists():
            p.unlink()
