"""Penyimpanan berkas unggahan — LOKAL di pod (keputusan owner 2026-09-12: "jangan pakai object storage, pakai lokal dulu").

URL publik TETAP `/api/uploads/<path>` (dilayani `server.py`), jadi frontend tidak berubah.
Berkas ditulis ke `UPLOAD_ROOT` (default /app/uploads). Object storage Emergent hanya dipakai bila
`FILE_STORAGE=object` DAN `EMERGENT_LLM_KEY` ada; bila gagal, tetap jatuh ke lokal — unggahan tidak pernah ditolak
karena penyimpanan.
"""
import logging
import mimetypes
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_PREFIX = "da-erp"
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT") or "/app/uploads")
LEGACY_ROOT = UPLOAD_ROOT

_storage_key = None


def _mode() -> str:
    return (os.environ.get("FILE_STORAGE") or "local").strip().lower()


def _key():
    return os.environ.get("EMERGENT_LLM_KEY")


def _local_path(path: str) -> Path:
    p = (UPLOAD_ROOT / path.lstrip("/")).resolve()
    if not str(p).startswith(str(UPLOAD_ROOT.resolve())):
        raise ValueError("path berkas tidak valid")
    return p


def init_storage(force: bool = False):
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    if not _key():
        raise RuntimeError("EMERGENT_LLM_KEY belum diset — object storage tidak aktif")
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": _key()}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def _full(path: str) -> str:
    return f"{APP_PREFIX}/{path.lstrip('/')}"


def _put_local(path: str, data: bytes) -> dict:
    p = _local_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return {"path": path, "size": len(data), "storage": "local", "url": f"/api/uploads/{path.lstrip('/')}"}


def put_object(path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    """Simpan berkas. `path` relatif tanpa prefix app (mis. `products/<id>/<uuid>.jpg`)."""
    if _mode() == "object" and _key():
        try:
            key = init_storage()
            resp = requests.put(f"{STORAGE_URL}/objects/{_full(path)}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
            if resp.status_code == 404:
                key = init_storage(force=True)
                resp = requests.put(f"{STORAGE_URL}/objects/{_full(path)}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
            resp.raise_for_status()
            out = resp.json()
            out.update({"url": f"/api/uploads/{path.lstrip('/')}", "storage": "object"})
            return out
        except Exception as e:  # noqa: BLE001
            logger.warning("object storage put gagal (%s) → simpan lokal: %s", path, e)
    return _put_local(path, data)


def get_object(path: str):
    """Ambil berkas → (bytes, content_type). Lokal dulu; object storage hanya bila mode object. None bila tidak ada."""
    try:
        p = _local_path(path)
    except ValueError:
        return None
    if p.is_file():
        return p.read_bytes(), mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    if _mode() == "object" and _key():
        try:
            key = init_storage()
            resp = requests.get(f"{STORAGE_URL}/objects/{_full(path)}", headers={"X-Storage-Key": key}, timeout=60)
            if resp.status_code == 200:
                return resp.content, resp.headers.get("Content-Type", "application/octet-stream")
        except Exception as e:  # noqa: BLE001
            logger.warning("object storage get gagal (%s): %s", path, e)
    return None
