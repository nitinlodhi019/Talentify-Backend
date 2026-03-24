"""
session_store.py
Replaces the in-memory dicts (resumes_db, screening_results_db, job_requirements_db)
with lightweight JSON files stored inside a per-session upload folder.

Session lifecycle:
  1. Client supplies a `session_id` header / query-param (UUID).
  2. On first write the folder  uploads/<session_id>/  is created.
  3. Three JSON "tables" live there:
       resumes.json          – uploaded & processed resume data
       screening.json        – latest screening results
       jobs.json             – saved job requirement sets
  4. Files are deleted explicitly via /api/clear_session_data,
     or automatically at startup if older than MAX_SESSION_AGE_SECONDS.
"""

import json
import os
import shutil
import time

UPLOAD_BASE = "uploads"
MAX_SESSION_AGE_SECONDS = 3600  # 1 hour


# ── folder helpers ──────────────────────────────────────────────────────────

def session_folder(session_id: str) -> str:
    return os.path.join(UPLOAD_BASE, session_id)


def ensure_session_folder(session_id: str) -> str:
    path = session_folder(session_id)
    os.makedirs(path, exist_ok=True)
    return path


def _table_path(session_id: str, table: str) -> str:
    return os.path.join(session_folder(session_id), f"{table}.json")


# ── generic read / write ────────────────────────────────────────────────────

def read_table(session_id: str, table: str) -> dict:
    path = _table_path(session_id, table)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_table(session_id: str, table: str, data: dict) -> None:
    ensure_session_folder(session_id)
    with open(_table_path(session_id, table), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ── resumes ─────────────────────────────────────────────────────────────────

def get_resumes(session_id: str) -> dict:
    return read_table(session_id, "resumes")


def save_resume(session_id: str, resume_id: str, data: dict) -> None:
    db = get_resumes(session_id)
    db[resume_id] = data
    write_table(session_id, "resumes", db)


# ── screening results ───────────────────────────────────────────────────────

def get_screening_results(session_id: str) -> dict:
    return read_table(session_id, "screening")


def save_screening_result(session_id: str, resume_id: str, data: dict) -> None:
    db = get_screening_results(session_id)
    db[resume_id] = data
    write_table(session_id, "screening", db)


def clear_screening_results(session_id: str) -> None:
    write_table(session_id, "screening", {})


# ── job requirements ─────────────────────────────────────────────────────────

def get_jobs(session_id: str) -> dict:
    return read_table(session_id, "jobs")


def save_job(session_id: str, job_id: str, data: dict) -> None:
    db = get_jobs(session_id)
    db[job_id] = data
    write_table(session_id, "jobs", db)


def get_job(session_id: str, job_id: str) -> dict | None:
    return get_jobs(session_id).get(job_id)


# ── session lifecycle ────────────────────────────────────────────────────────

def clear_session(session_id: str) -> None:
    """Delete the entire session folder (files + JSON tables)."""
    path = session_folder(session_id)
    if os.path.exists(path):
        shutil.rmtree(path)


def cleanup_old_sessions() -> None:
    """Called at startup to remove sessions older than MAX_SESSION_AGE_SECONDS."""
    if not os.path.exists(UPLOAD_BASE):
        return
    now = time.time()
    for name in os.listdir(UPLOAD_BASE):
        path = os.path.join(UPLOAD_BASE, name)
        if os.path.isdir(path):
            if now - os.path.getctime(path) > MAX_SESSION_AGE_SECONDS:
                shutil.rmtree(path)
                print(f"🗑️  Removed old session folder: {name}")