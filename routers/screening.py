"""
routers/screening.py
Resume upload, screening, dashboard, download and session-clear endpoints.

Storage model (replaces in-memory dicts):
  Every request carries a `session_id` header.
  All data lives in  uploads/<session_id>/
    resumes.json     – processed resume data  (was resumes_db)
    screening.json   – screening results       (was screening_results_db)
    jobs.json        – job requirement sets    (was job_requirements_db)
  Actual resume files are stored as
    uploads/<session_id>/<uuid>_<original_filename>
"""

import os
import uuid
import zipfile
from io import BytesIO
from mimetypes import guess_type

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from dotenv import load_dotenv

import session_store as store
from text_extractor import extract_text_from_file
from text_processor import preprocess_text, extract_skills_from_text, categorize_resume
from resume_matcher import calculate_match_score_enhanced

from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://localhost:8000")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "dummy_key")
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    supabase = None


def check_and_increment_usage(user_id: str, count: int) -> tuple[bool, str, int, int]:
    """
    Checks if user has enough quota, then increments by `count`.
    Returns: (allowed, message, resumes_used, resumes_limit)
    """
    if not supabase:
        return True, "ok", 0, 50  # fail open if DB is down

    resp = supabase.table("user_usage").select(
        "id", "resumes_used", "resumes_limit"
    ).eq("user_id", user_id).execute()

    if not resp.data:
        # Row missing — auto-create it (safety net)
        supabase.table("user_usage").insert({
            "user_id": user_id,
            "resumes_used": 0,
            "resumes_limit": 50,
        }).execute()
        row = {"resumes_used": 0, "resumes_limit": 50}
    else:
        row = resp.data[0]

    used  = row["resumes_used"]
    limit = row["resumes_limit"]
    remaining = limit - used

    if count > remaining:
        msg = (
            f"Resume limit reached. You have used {used}/{limit} resumes. "
            f"Only {remaining} remaining, but tried to upload {count}."
        )
        return False, msg, used, limit

    # Increment atomically
    supabase.table("user_usage").update({
        "resumes_used": used + count
    }).eq("user_id", user_id).execute()

    return True, "ok", used + count, limit

load_dotenv()

router = APIRouter()

HF_API_KEY = os.environ.get("HF_API_KEY")
if not HF_API_KEY:
    print("WARNING: HF_API_KEY not set. Hugging Face LLM features will be disabled.")


# ── Session ID dependency helper ─────────────────────────────────────────────

def require_session(x_session_id: str = Header(..., alias="x-session-id")) -> str:
    """
    Clients must send an  x-session-id  header containing a UUID they generated
    (or received from a previous call). All data for a request-set is scoped
    to that session folder.
    """
    return x_session_id


# ── Request / Response schemas ────────────────────────────────────────────────

class JobRequirementsRequest(BaseModel):
    user_id: str
    job_description: str
    skills: list[str]
    department: str | None = None
    experience_required: str | None = None


class ScreenRequest(BaseModel):
    job_id: str
    resume_ids: list[str]


class DownloadResumeRequest(BaseModel):
    filepath: str


class FilteredDownloadRequest(BaseModel):
    filtered_resume_ids: list[str]


# ── Job Requirements ──────────────────────────────────────────────────────────

@router.post("/job_requirements")
def save_job_requirements(
    body: JobRequirementsRequest,
    session_id: str = Header(..., alias="x-session-id"),
):
    job_id = str(uuid.uuid4())
    store.save_job(session_id, job_id, {
        "user_id": body.user_id,
        "job_description": body.job_description,
        "department": body.department,
        "skills": body.skills,
        "experience_required": body.experience_required,
    })
    print(f"Job requirements saved for session {session_id} with job_id: {job_id}")
    return JSONResponse({"message": "Job requirements saved temporarily", "job_id": job_id}, 201)


# ── Upload Resumes ────────────────────────────────────────────────────────────

@router.post("/upload_resumes")
async def upload_resumes(
    files: list[UploadFile] = File(...),
    user_id: str = Form(...),
    session_id: str = Header(..., alias="x-session-id"),
):
    valid_files = [f for f in files if f.filename]
    if not valid_files:
        return JSONResponse({"message": "No valid files provided"}, 400)

    # ── QUOTA CHECK ──────────────────────────────────────────────────────────
    allowed, msg, used, limit = check_and_increment_usage(user_id, len(valid_files))
    if not allowed:
        return JSONResponse({
            "message": msg,
            "resumes_used": used,
            "resumes_limit": limit,
        }, 429)  # 429 Too Many Requests is the right status here
    # ────────────────────────────────────────────────────────────────────────

    folder = store.ensure_session_folder(session_id)
    uploaded_ids: list[str] = []

    for file in valid_files:
        original_filename = file.filename
        unique_filename = f"{uuid.uuid4()}_{original_filename}"
        filepath = os.path.join(folder, unique_filename)

        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)

        raw_text        = extract_text_from_file(filepath)
        processed_text  = preprocess_text(raw_text)
        extracted_skills = extract_skills_from_text(processed_text)
        categorized_field = categorize_resume(processed_text)

        resume_id = str(uuid.uuid4())
        store.save_resume(session_id, resume_id, {
            "filename": original_filename,
            "filepath": unique_filename,
            "raw_text": raw_text,
            "processed_text": processed_text,
            "extracted_skills": extracted_skills,
            "categorized_field": categorized_field,
        })
        uploaded_ids.append(resume_id)

    return JSONResponse({
        "message": "Resumes uploaded and processed",
        "resume_ids": uploaded_ids,
        "resumes_used": used,       # ← handy for the frontend to update its UI
        "resumes_limit": limit,
    }, 200)

# ── Screen Resumes ────────────────────────────────────────────────────────────

@router.post("/screen_resumes")
def screen_resumes(
    body: ScreenRequest,
    session_id: str = Header(..., alias="x-session-id"),
):
    job_req = store.get_job(session_id, body.job_id)
    if not job_req:
        return JSONResponse(
            {"message": "Job requirements not found or session expired. Please re-enter job details."}, 404
        )

    job_description_text = job_req["job_description"]
    required_skills = job_req["skills"]
    required_department = job_req["department"]
    experience_required = job_req["experience_required"]

    store.clear_screening_results(session_id)
    resumes = store.get_resumes(session_id)
    results = []

    for resume_id in body.resume_ids:
        if resume_id not in resumes:
            continue

        resume_data = resumes[resume_id]
        resume_processed_text = resume_data["processed_text"]
        resume_extracted_skills = resume_data["extracted_skills"]
        resume_categorized_field = resume_data["categorized_field"]

        match_score, matched_skills = calculate_match_score_enhanced(
            job_description_text,
            required_skills,
            experience_required,
            resume_processed_text,
            resume_extracted_skills,
            HF_API_KEY,
        )

        department_match_factor = 1.0
        if required_department and required_department.lower() in resume_processed_text.lower():
            department_match_factor = 1.05

        final_score = min(int(match_score * department_match_factor), 100)

        result = {
            "job_id": body.job_id,
            "resume_id": resume_id,
            "filename": resume_data["filename"],
            "filepath": resume_data["filepath"],
            "raw_text": resume_data["raw_text"],
            "match_score": final_score,
            "matched_skills": matched_skills,
            "department": required_department,
            "experience_level": experience_required,
            "categorized_field": resume_categorized_field,
        }
        store.save_screening_result(session_id, resume_id, result)
        results.append(result)

    return JSONResponse({"message": "Screening complete", "results": results}, 200)


# ── Dashboard Data ────────────────────────────────────────────────────────────

@router.get("/dashboard_data")
def get_dashboard_data(
    sort_by: str = "score",
    session_id: str = Header(..., alias="x-session-id"),
):
    results = list(store.get_screening_results(session_id).values())

    if sort_by == "score":
        results.sort(key=lambda x: x["match_score"], reverse=True)
    elif sort_by == "name":
        results.sort(key=lambda x: x["filename"])

    formatted = [
        {
            "id": r["resume_id"],
            "name": r["filename"].rsplit(".", 1)[0],
            "matchScore": r["match_score"],
            "matchedSkills": r["matched_skills"],
            "department": r.get("department", "N/A"),
            "category": r.get("categorized_field", "Uncategorized"),
            "experienceLevel": r.get("experience_level", "Not Specified"),
            "shortlisted": False,
        }
        for r in results
    ]
    return JSONResponse(formatted, 200)


# ── Get Raw Resume Text ───────────────────────────────────────────────────────

@router.get("/resume/{resume_id}")
def get_resume_raw_text(
    resume_id: str,
    session_id: str = Header(..., alias="x-session-id"),
):
    resumes = store.get_resumes(session_id)
    if resume_id in resumes:
        return JSONResponse({"content": resumes[resume_id]["raw_text"]}, 200)
    return JSONResponse({"message": "Resume not found"}, 404)


# ── Download All Resumes for a Job ────────────────────────────────────────────

@router.get("/download_all_resumes/{job_id}")
def download_all_resumes_for_job(
    job_id: str,
    session_id: str = Header(..., alias="x-session-id"),
):
    folder = store.session_folder(session_id)
    screening = store.get_screening_results(session_id)
    to_download = [r for r in screening.values() if r["job_id"] == job_id]

    if not to_download:
        return JSONResponse({"message": "No resumes found for this job ID."}, 404)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in to_download:
            full_path = os.path.join(folder, r["filepath"])
            if os.path.exists(full_path):
                zf.write(full_path, arcname=r["filename"])
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=all_resumes_{job_id}.zip"},
    )


# ── Download Single Resume ────────────────────────────────────────────────────

@router.post("/download_resume")
def download_resume_file(
    body: DownloadResumeRequest,
    session_id: str = Header(..., alias="x-session-id"),
):
    unique_filename = body.filepath
    if not unique_filename:
        return JSONResponse({"message": "Filepath is required"}, 400)

    folder = store.session_folder(session_id)
    full_path = os.path.join(folder, unique_filename)

    # Security: file must be inside the session folder
    if not os.path.abspath(full_path).startswith(os.path.abspath(folder) + os.sep):
        return JSONResponse({"message": "Invalid file path"}, 400)

    if not os.path.exists(full_path):
        return JSONResponse({"message": "File not found on server"}, 404)

    original_filename = unique_filename.split("_", 1)[-1]
    mimetype, _ = guess_type(original_filename)

    with open(full_path, "rb") as f:
        content = f.read()

    return Response(
        content=content,
        media_type=mimetype or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{original_filename}"'},
    )


# ── Download All Filtered Resumes ─────────────────────────────────────────────

@router.post("/download_all_filtered_resumes")
def download_all_filtered_resumes(
    body: FilteredDownloadRequest,
    session_id: str = Header(..., alias="x-session-id"),
):
    if not body.filtered_resume_ids:
        return JSONResponse({"message": "No filtered resumes to download."}, 404)

    folder = store.session_folder(session_id)
    screening = store.get_screening_results(session_id)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for resume_id in body.filtered_resume_ids:
            result = screening.get(resume_id)
            if not result:
                print(f"Resume ID {resume_id} not found in screening results.")
                continue

            unique_filename = result.get("filepath")
            original_filename = result.get("filename")
            if not unique_filename or not original_filename:
                continue

            full_path = os.path.join(folder, unique_filename)

            # Security check
            if not os.path.abspath(full_path).startswith(os.path.abspath(folder) + os.sep):
                print(f"Skipping file outside session folder: {full_path}")
                continue

            if os.path.exists(full_path):
                zf.write(full_path, arcname=original_filename)
            else:
                print(f"File not found: {full_path}")

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=filtered_resumes.zip"},
    )

@router.get("/usage/{user_id}")
def get_usage(user_id: str):
    if not supabase:
        return JSONResponse({"message": "Database not connected"}, 500)

    resp = supabase.table("user_usage").select(
        "resumes_used", "resumes_limit", "last_reset"
    ).eq("user_id", user_id).execute()

    if not resp.data:
        return JSONResponse({"message": "Usage record not found"}, 404)

    row = resp.data[0]
    return JSONResponse({
        "resumes_used":  row["resumes_used"],
        "resumes_limit": row["resumes_limit"],
        "last_reset":    row["last_reset"],
        "remaining":     row["resumes_limit"] - row["resumes_used"],
    }, 200)

# ── Clear Session Data ────────────────────────────────────────────────────────

@router.post("/clear_session_data")
def clear_session_data(
    session_id: str = Header(..., alias="x-session-id"),
):
    store.clear_session(session_id)
    print(f"Session data cleared for session_id: {session_id}")
    return JSONResponse({"message": "Session data cleared successfully"}, 200)