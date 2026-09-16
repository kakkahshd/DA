"""Iter 202 — Regressi BOM POTONGAN (INV-F46) + endpoint costing/bom/cutting/rahaza."""
import os
import pytest
import requests
from pymongo import MongoClient

BASE = "http://localhost:8001"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

client = MongoClient(MONGO_URL)
db = client[DB_NAME]


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@garment.com", "password": "Admin@123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def da1101():
    m = db["rahaza_models"].find_one({"code": "DA-1101", "active": True})
    assert m, "Model DA-1101 tidak ditemukan"
    return m


def _mid(m):
    return m.get("id") or m.get("_id")


# ---------------- P1/P2: DB invariants ----------------
def test_all_active_boms_use_one_cut_panel():
    """Setiap BOM aktif punya tepat 1 baris materials is_cut_panel=true qty=1 unit=pcs code CUT-, tanpa baris fabric non-cut."""
    boms = list(db["rahaza_boms"].find({"is_active": True}))
    assert len(boms) > 0
    bad = []
    for b in boms:
        mats = b.get("materials") or []
        cut = [m for m in mats if m.get("is_cut_panel")]
        fabric_non_cut = [m for m in mats if (m.get("material_type") == "fabric") and not m.get("is_cut_panel")]
        if len(cut) != 1:
            bad.append(("cut_count", b.get("_id"), len(cut)))
            continue
        c = cut[0]
        if float(c.get("qty") or 0) != 1.0:
            bad.append(("qty", b.get("_id"), c.get("qty")))
        if (c.get("unit") or "").lower() != "pcs":
            bad.append(("unit", b.get("_id"), c.get("unit")))
        if not str(c.get("code") or "").startswith("CUT-"):
            bad.append(("code", b.get("_id"), c.get("code")))
        if fabric_non_cut:
            bad.append(("fabric_non_cut", b.get("_id"), len(fabric_non_cut)))
    assert not bad, f"BOM tidak sesuai kebijakan potongan: {bad[:5]} total={len(bad)}"


def test_master_cut_panels_472():
    q = {"is_cut_panel": True}
    total = db["rahaza_materials"].count_documents(q)
    assert total == 472, f"Total master potongan = {total}, seharusnya 472"
    # required fields terisi
    missing = list(db["rahaza_materials"].find({
        "is_cut_panel": True,
        "$or": [
            {"model_id": {"$in": [None, ""]}},
            {"color_code": {"$in": [None, ""]}},
            {"size_code": {"$in": [None, ""]}},
            {"source_material_code": {"$in": [None, ""]}},
        ]
    }, {"_id": 1, "code": 1}).limit(5))
    assert not missing, f"Master potongan field wajib kosong: {missing}"


# ---------------- P3: costing endpoint ----------------
def test_costing_model_da1101_gap_panel_unvalued(auth, da1101):
    r = requests.get(f"{BASE}/api/costing/models/{_mid(da1101)}", headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()
    # gaps mengandung panel_unvalued
    def collect_gaps(node):
        out = []
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "gaps" and isinstance(v, list):
                    out.extend(v)
                elif isinstance(v, (dict, list)):
                    out.extend(collect_gaps(v))
        elif isinstance(node, list):
            for it in node:
                out.extend(collect_gaps(it))
        return out
    gaps = collect_gaps(data)
    codes = [g.get("code") for g in gaps if isinstance(g, dict)]
    assert "panel_unvalued" in codes, f"gap 'panel_unvalued' tidak ditemukan. codes={set(codes)}"
    # ada pesan menyebut cutting
    msgs = " | ".join([str(g.get("message") or g.get("msg") or "") for g in gaps if isinstance(g, dict) and g.get("code") == "panel_unvalued"])
    assert "cutting" in msgs.lower() or "potongan" in msgs.lower(), f"pesan tidak menyebut cutting: {msgs}"

    # cari biaya bahan ukuran ALLSIZE = 0
    def find_allsize(node):
        if isinstance(node, dict):
            sc = str(node.get("size_code") or node.get("size") or "").upper()
            if sc == "ALLSIZE" and ("material_cost" in node or "material_cost_per_pcs" in node or "hpp_material" in node):
                return node
            for v in node.values():
                r = find_allsize(v)
                if r is not None:
                    return r
        elif isinstance(node, list):
            for it in node:
                r = find_allsize(it)
                if r is not None:
                    return r
        return None
    allsize = find_allsize(data)
    if allsize is not None:
        val = allsize.get("material_cost", allsize.get("material_cost_per_pcs", allsize.get("hpp_material")))
        assert float(val or 0) == 0.0, f"biaya bahan ALLSIZE bukan 0: {val}"


# ---------------- BOM matrix ----------------
def test_rahaza_bom_matrix_da1101(auth, da1101):
    r = requests.get(f"{BASE}/api/rahaza/models/{_mid(da1101)}/bom", headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()
    # find matrix row for ALLSIZE
    rows = data.get("matrix") or data.get("rows") or data.get("bom_matrix") or []
    if not rows and isinstance(data, list):
        rows = data
    allsize_rows = [r for r in rows if str(r.get("size_code") or r.get("size") or "").upper() == "ALLSIZE"]
    assert allsize_rows, f"Tidak ada baris ALLSIZE. keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
    row = allsize_rows[0]
    pc = row.get("panel_code") or ""
    assert pc.startswith("CUT-DA-1101-") and pc.endswith("-ALLSIZE"), f"panel_code={pc}"
    psf = row.get("panel_source_fabric") or row.get("panel_source_material_code") or ""
    assert psf.startswith("KN-") or psf.startswith("KN"), f"panel_source_fabric={psf}"
    assert float(row.get("total_material_kg_per_pcs") or 0) == 0.0


# ---------------- Cutting BOM requirement ----------------
def test_cutting_bom_requirement_da1101(auth, da1101):
    # find ALLSIZE size id
    size = db["rahaza_sizes"].find_one({"code": "ALLSIZE"}) or db["rahaza_sizes"].find_one({"name": "ALLSIZE"})
    assert size, "size ALLSIZE tidak ditemukan"
    r = requests.get(
        f"{BASE}/api/cutting/bom-requirement",
        params={"model_id": _mid(da1101), "size_id": size.get('id') or size['_id'], "qty_pcs": 10},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("has_bom") is True
    assert data.get("plan_manual") is True
    panel = data.get("panel") or {}
    assert str(panel.get("code") or "").startswith("CUT-"), f"panel.code={panel.get('code')}"
    gap_codes = [g.get("code") for g in (data.get("gaps") or []) if isinstance(g, dict)]
    assert "bom_without_fabric" not in gap_codes
    assert "input_not_in_bom" not in gap_codes


# ---------------- Rahaza BOM GET + roundtrip PUT ----------------
def test_rahaza_bom_get_and_put_roundtrip(auth):
    # pick any active BOM
    bom = db["rahaza_boms"].find_one({"is_active": True})
    assert bom
    bid = bom.get('id') or bom['_id']
    r = requests.get(f"{BASE}/api/rahaza/boms/{bid}", headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()
    mats = data.get("materials") or []
    assert mats and mats[0].get("is_cut_panel") is True
    assert mats[0].get("source_material_code")
    # PUT identical
    r2 = requests.put(f"{BASE}/api/rahaza/boms/{bid}", headers=auth, json={"materials": mats})
    assert r2.status_code == 200, r2.text
    # verify penanda tidak hilang
    r3 = requests.get(f"{BASE}/api/rahaza/boms/{bid}", headers=auth)
    assert r3.status_code == 200
    m3 = (r3.json().get("materials") or [])
    assert m3 and m3[0].get("is_cut_panel") is True, "is_cut_panel hilang setelah PUT"
