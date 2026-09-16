"""Endpoint cron platform (.emergent/crons.yml) + pemicu manual Finance.

- POST /api/cron/mark-overdue          → AR/AP lewat jatuh tempo → status `overdue` (M-07)
- POST /api/cron/fg-valuation-check    → selisih Nilai Persediaan FG vs GL belum terjelaskan → notifikasi Finance
Keduanya: Bearer WEBHOOK_CRON_SECRET, idempoten per X-Webhook-Id, kerja di background.
"""
import asyncio
import hmac
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from auth import require_auth
from database import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cron", tags=["cron"])
RUNS = "cron_runs"
FIN_ROLES = ["accounting", "staff_keuangan", "manager_keuangan", "admin", "superadmin", "owner"]


def _now(): return datetime.now(timezone.utc)


def _verify_secret(request: Request):
    secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
    auth = request.headers.get("Authorization") or ""
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(401, "Unauthorized")


async def _require_fin(request: Request):
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    perms = user.get("_permissions") or []
    if role in FIN_ROLES or "*" in perms or "finance.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh permission finance.")


async def _start_run(db, job: str, run_id: str, trigger: str) -> Optional[dict]:
    await db[RUNS].create_index("run_id", unique=True)
    doc = {"id": str(uuid.uuid4()), "job": job, "run_id": run_id, "trigger": trigger, "status": "running", "started_at": _now()}
    try:
        await db[RUNS].insert_one(doc)
    except Exception:  # duplicate run_id
        return None
    doc.pop("_id", None)
    return doc


async def _finish_run(db, run_id: str, result: dict, error: str = None):
    await db[RUNS].update_one({"run_id": run_id}, {"$set": {"status": "error" if error else "ok", "result": result,
                                                            "error": error, "finished_at": _now()}})


# ── PEKERJAAN 1: status overdue otomatis (M-07) ───────────────────────────────
async def run_mark_overdue(db) -> dict:
    today = date.today().isoformat()
    ar_q = {"status": {"$in": ["issued", "sent"]}, "due_date": {"$lt": today}, "$or": [{"amount_due": {"$gt": 0}}, {"balance": {"$gt": 0}}]}
    ar_rows = await db.rahaza_ar_invoices.find(ar_q, {"_id": 0, "id": 1, "invoice_number": 1, "balance": 1, "amount_due": 1, "customer_name": 1}).to_list(5000)
    if ar_rows:
        await db.rahaza_ar_invoices.update_many({"id": {"$in": [r["id"] for r in ar_rows]}},
                                               {"$set": {"status": "overdue", "overdue_marked_at": _now(), "updated_at": _now()}})
    ap_q = {"status": "sent", "due_date": {"$lt": today}, "balance": {"$gt": 0}}
    ap_rows = await db.rahaza_ap_invoices.find(ap_q, {"_id": 0, "id": 1, "invoice_number": 1, "balance": 1, "vendor_name": 1}).to_list(5000)
    if ap_rows:
        await db.rahaza_ap_invoices.update_many({"id": {"$in": [r["id"] for r in ap_rows]}},
                                               {"$set": {"status": "overdue", "overdue_marked_at": _now(), "updated_at": _now()}})
    ar_total = round(sum(float(r.get("amount_due") if r.get("amount_due") is not None else r.get("balance") or 0) for r in ar_rows), 2)
    ap_total = round(sum(float(r.get("balance") or 0) for r in ap_rows), 2)
    res = {"date": today, "ar_marked": len(ar_rows), "ar_total": ar_total, "ap_marked": len(ap_rows), "ap_total": ap_total,
           "ar_invoices": [r.get("invoice_number") for r in ar_rows][:50], "ap_invoices": [r.get("invoice_number") for r in ap_rows][:50]}
    if ar_rows or ap_rows:
        from utils.notif_unified import notif_insert
        await notif_insert(db, type="rahaza", subtype="invoice_overdue", severity="warning",
                           title="Invoice lewat jatuh tempo",
                           body=f"{len(ar_rows)} invoice piutang (Rp {ar_total:,.0f}) dan {len(ap_rows)} tagihan hutang (Rp {ap_total:,.0f}) ditandai overdue per {today}.",
                           target_roles=FIN_ROLES, source_type="cron", source_ref=f"overdue:{today}", meta=res)
    return res


# ── PEKERJAAN 2: rekonsiliasi Nilai Persediaan FG vs GL ──────────────────────
async def run_fg_valuation_check(db) -> dict:
    from routes.rahaza_fin_reports import compute_fg_valuation
    today = date.today().isoformat()
    rep = await compute_fg_valuation(db, today)
    t = rep["totals"]
    res = {"date": today, "layer_value": t["layer_value"], "gl_balance": t["gl_balance"], "difference": t["difference"],
           "unposted_value": t["unposted_value"], "unposted_layers": t["unposted_layers"],
           "unexplained_difference": t["unexplained_difference"], "reconciled": rep["reconciled"], "explained": rep["explained"],
           "notified": False}
    if not rep["explained"]:
        from utils.notif_unified import notif_insert
        ref = f"fgval:{today}"
        if not await db.notifications.find_one({"source_ref": ref}):
            await notif_insert(db, type="rahaza", subtype="fg_valuation_unexplained", severity="error",
                               title="Selisih Nilai Persediaan FG vs GL belum terjelaskan",
                               body=(f"Per {today}: nilai lapisan FIFO Rp {t['layer_value']:,.0f} vs saldo GL 1-1404 Rp {t['gl_balance']:,.0f}. "
                                     f"Selisih Rp {t['difference']:,.0f}, belum terjelaskan Rp {t['unexplained_difference']:,.0f} "
                                     f"(lapisan belum berjurnal: {t['unposted_layers']}). Buka Laporan Keuangan → Nilai Persediaan FG."),
                               target_roles=FIN_ROLES, source_type="cron", source_ref=ref, meta=res)
            res["notified"] = True
    return res


JOBS = {"mark-overdue": run_mark_overdue, "fg-valuation-check": run_fg_valuation_check}


async def _run_job(job: str, run_id: str):
    db = get_db()
    try:
        res = await JOBS[job](db)
        await _finish_run(db, run_id, res)
    except Exception as e:  # noqa: BLE001
        log.exception("[cron] %s gagal", job)
        await _finish_run(db, run_id, {}, error=str(e))


async def _webhook(job: str, request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _verify_secret(request)
    try:
        body = await request.json() if await request.body() else {}
    except Exception:
        raise HTTPException(400, "Body JSON tidak valid")
    run_id = request.headers.get("X-Webhook-Id") or (body or {}).get("run_id") or f"{job}-{_now().strftime('%Y%m%dT%H%M')}"
    run = await _start_run(get_db(), job, run_id, "webhook")
    if not run:
        return {"status": "duplicate", "run_id": run_id}
    background.add_task(_run_job, job, run_id)
    return {"status": "accepted", "run_id": run_id}


@router.post("/mark-overdue")
async def cron_mark_overdue(request: Request, background: BackgroundTasks):
    return await _webhook("mark-overdue", request, background)


@router.post("/fg-valuation-check")
async def cron_fg_valuation_check(request: Request, background: BackgroundTasks):
    return await _webhook("fg-valuation-check", request, background)


# ── PEMICU MANUAL & RIWAYAT (Finance) ────────────────────────────────────────
@router.post("/{job}/run-now")
async def run_now(job: str, request: Request):
    await _require_fin(request)
    if job not in JOBS:
        raise HTTPException(404, "Job tidak dikenal")
    db = get_db()
    run_id = f"{job}-manual-{_now().strftime('%Y%m%dT%H%M%S%f')}"
    await _start_run(db, job, run_id, "manual")
    try:
        res = await JOBS[job](db)
    except Exception as e:  # noqa: BLE001
        await _finish_run(db, run_id, {}, error=str(e))
        raise HTTPException(500, f"Job gagal: {e}")
    await _finish_run(db, run_id, res)
    return {"run_id": run_id, "result": res}


@router.get("/runs")
async def list_runs(request: Request, job: Optional[str] = None, limit: int = 10):
    await _require_fin(request)
    db = get_db()
    q = {"job": job} if job else {}
    rows = await db[RUNS].find(q, {"_id": 0}).sort("started_at", -1).to_list(min(limit, 100))
    for r in rows:
        for k in ("started_at", "finished_at"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
    return rows
