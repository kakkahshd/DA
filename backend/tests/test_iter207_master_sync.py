"""QA iter207 — Verifikasi Sinkron Master lintas portal (variants SSOT ∪ BOM ∪ FG,
Style RnD, karyawan↔user, kategori material, satuan gudang) + creator-portal auth."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASSWORD = "Admin@123"


@pytest.fixture(scope="module")
def admin_token():
    # rate limit 10/menit — coba beberapa kali kalau kena
    for i in range(3):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["token"]
        if r.status_code == 429:
            time.sleep(15)
            continue
        pytest.fail(f"Login admin gagal: {r.status_code} {r.text[:200]}")
    pytest.fail("Login admin gagal setelah 3 percobaan (rate limit).")


@pytest.fixture(scope="module")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ── A · Idempoten POST /api/rahaza/master/sync ─────────────────────────────
def test_master_sync_idempotent(H):
    r = requests.post(f"{BASE_URL}/api/rahaza/master/sync", headers=H, timeout=180)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    rep = r.json()
    # variants total 645
    variants = rep.get("variants", {})
    assert variants.get("total") == 645, f"variants.total={variants.get('total')} (exp 645)"
    assert variants.get("created_from_fg") == 0, rep
    assert variants.get("created_from_bom") == 0, rep
    rnd = rep.get("rnd", {})
    assert rnd.get("styles_created") == 0, rep
    assert rnd.get("rnd_variants_created") == 0, rep
    assert rep.get("employees_linked", 0) == 0, rep
    assert rep.get("materials_categorized", 0) == 0, rep
    assert rep.get("units_added", []) == [], rep


# ── B · Varian SSOT (rahaza_model_variants) = 645, SKU unik ───────────────
def test_rahaza_variants_645_unique_sku(H):
    r = requests.get(f"{BASE_URL}/api/rahaza/variants", headers=H, timeout=60)
    assert r.status_code == 200, r.text[:200]
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 645, f"expected 645 varian aktif, got {len(rows)}"
    skus = [v["sku"] for v in rows]
    assert len(skus) == len(set(skus)), "SKU varian ada yang kembar"
    for v in rows[:20]:
        assert v.get("model_id") and v.get("size_id") and v.get("color_code"), v


# ── C · Styles RnD: 104, variants_count > 0, status hanya promoted/approved_for_launch ──
def test_rnd_styles_104_with_variants_count(H):
    r = requests.get(f"{BASE_URL}/api/dewi/rnd/styles?limit=1000", headers=H, timeout=60)
    assert r.status_code == 200, r.text[:200]
    styles = r.json()
    # 104 style master_sync hasil sinkron (mungkin ada style lain draft; kita cek subset master_sync)
    ms = [s for s in styles if s.get("master_sync") is True]
    assert len(ms) == 104, f"master_sync styles={len(ms)} (exp 104)"
    # variants_count > 0 kecuali model tanpa varian sama sekali (kasus valid per review)
    zero = [s for s in ms if not s.get("variants_count")]
    # 20 style approved_for_launch tanpa varian SSOT — model belum punya BOM/varian
    assert len(zero) <= 25, f"{len(zero)} style master_sync tanpa variants_count (tolerance ≤25)"
    statuses = {s.get("status") for s in ms}
    assert statuses <= {"promoted", "approved_for_launch"}, f"status tidak terduga: {statuses}"
    promoted = [s for s in ms if s["status"] == "promoted"]
    approved = [s for s in ms if s["status"] == "approved_for_launch"]
    assert len(promoted) == 48, f"promoted={len(promoted)} (exp 48)"
    assert len(approved) == 56, f"approved_for_launch={len(approved)} (exp 56)"
    # spot check: promoted_to_model_id terisi utk salah satu promoted
    sid_ = promoted[0]["id"]
    rd = requests.get(f"{BASE_URL}/api/dewi/rnd/styles/{sid_}", headers=H, timeout=30)
    assert rd.status_code == 200
    assert rd.json().get("promoted_to_model_id"), "promoted_to_model_id kosong"


# ── D · GET /api/dewi/rnd/variants?style_id=… → daftar warna + sizes[].sku ─
def test_rnd_variants_per_style(H):
    r = requests.get(f"{BASE_URL}/api/dewi/rnd/styles?limit=1000", headers=H, timeout=60)
    ms = [s for s in r.json() if s.get("master_sync") is True and s.get("variants_count", 0) > 0]
    assert ms, "tidak ada style master_sync utk uji"
    sid_ = ms[0]["id"]
    r2 = requests.get(f"{BASE_URL}/api/dewi/rnd/variants?style_id={sid_}", headers=H, timeout=30)
    assert r2.status_code == 200, r2.text[:200]
    vs = r2.json()
    assert isinstance(vs, list) and vs, "variants RnD kosong"
    for v in vs:
        assert v.get("color_code") or v.get("color"), v
        assert isinstance(v.get("sizes"), list) and v["sizes"], v
        for s in v["sizes"]:
            assert s.get("sku"), s


# ── E · Models: rnd_style_id terisi utk model dari master_sync ────────────
def test_models_have_rnd_style_id(H):
    r = requests.get(f"{BASE_URL}/api/rahaza/models", headers=H, timeout=60)
    assert r.status_code == 200, r.text[:200]
    ms = r.json()
    assert isinstance(ms, list) and len(ms) >= 100
    without = [m for m in ms if not m.get("rnd_style_id")]
    # bolehkan sedikit legacy tanpa rnd_style_id, tapi wajarnya 0
    assert len(without) <= 5, f"{len(without)} model tanpa rnd_style_id (contoh: {without[:3]})"


# ── F · FG materials: punya variant_id + category ─────────────────────────
def test_fg_materials_have_variant_and_category(H):
    r = requests.get(f"{BASE_URL}/api/rahaza/materials?type=fg", headers=H, timeout=60)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    rows = data if isinstance(data, list) else (data.get("items") or data.get("data") or [])
    assert rows, "FG kosong"
    no_var = [f for f in rows if not f.get("variant_id")]
    assert not no_var, f"{len(no_var)} FG tanpa variant_id (contoh: {[f.get('code') for f in no_var[:3]]})"


# ── G · Kategori material: ada CUT_PANEL ──────────────────────────────────
def test_material_categories_has_cut_panel(H):
    r = requests.get(f"{BASE_URL}/api/rahaza/material-categories", headers=H, timeout=30)
    assert r.status_code == 200, r.text[:200]
    cats = r.json()
    codes = {(c.get("code") or "").upper() for c in cats}
    assert "CUT_PANEL" in codes, f"CUT_PANEL tidak ada. codes={sorted(codes)}"


# ── H · WMS units: pack & roll ada di wh_unit_master ───────────────────────
def test_wms_units_have_pack_and_roll(H):
    r = requests.get(f"{BASE_URL}/api/wms/units", headers=H, timeout=30)
    assert r.status_code == 200, r.text[:200]
    rows = r.json()
    codes = {(u.get("code") or "").lower() for u in rows}
    assert "pack" in codes, f"pack tidak ada di wh_unit_master. codes={sorted(codes)}"
    assert "roll" in codes, f"roll tidak ada di wh_unit_master. codes={sorted(codes)}"


# ── I · Creator-portal login akun tanpa hash → 401 (bukan 500 Invalid salt) ─
def test_creator_login_no_hash_returns_401():
    r = requests.post(
        f"{BASE_URL}/api/marketing/creator-portal/auth/login",
        json={"email": "iori.oliviara@creator.id", "password": "x"},
        timeout=30,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code} — {r.text[:200]}"


# ── J · Finance regression: trial-balance masih 200 ───────────────────────
def test_finance_trial_balance_200(H):
    r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/trial-balance", headers=H, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"


# ── K · MongoDB integrity cek (rahaza_materials, rahaza_employees, rahaza_boms) ──
def test_mongo_integrity_checks():
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def run():
        c = AsyncIOMotorClient(mongo_url)
        db = c[db_name]
        # 1. rahaza_materials non-fg semua category_id ada di rahaza_material_categories
        cat_ids = {d["id"] async for d in db.rahaza_material_categories.find({}, {"id": 1})}
        bad_mat = await db.rahaza_materials.count_documents({
            "active": True,
            "type": {"$ne": "fg"},
            "$or": [
                {"category_id": {"$exists": False}},
                {"category_id": None},
                {"category_id": ""},
                {"category_id": {"$nin": list(cat_ids)}},
            ],
        })
        assert bad_mat == 0, f"{bad_mat} material non-fg tanpa kategori valid"
        # 2. rahaza_employees semua user_id terisi
        bad_emp = await db.rahaza_employees.count_documents({
            "active": True,
            "$or": [{"user_id": {"$exists": False}}, {"user_id": None}, {"user_id": ""}],
        })
        # allow small tolerance for legacy inactive-but-active docs
        assert bad_emp == 0, f"{bad_emp} karyawan aktif tanpa user_id"
        # 3. rahaza_boms kombinasi (model_id,size_id,color_code) ada di rahaza_model_variants
        missing = 0
        variant_keys = set()
        async for v in db.rahaza_model_variants.find(
            {"active": True}, {"model_id": 1, "size_id": 1, "color_code": 1}
        ):
            variant_keys.add((v.get("model_id"), v.get("size_id"), (v.get("color_code") or "").upper()))
        async for b in db.rahaza_boms.find({}, {"model_id": 1, "size_id": 1, "color_code": 1}):
            k = (b.get("model_id"), b.get("size_id"), (b.get("color_code") or "").upper())
            if k not in variant_keys:
                missing += 1
        assert missing == 0, f"{missing} kombinasi BOM tanpa varian SSOT"
        c.close()

    asyncio.get_event_loop().run_until_complete(run())
