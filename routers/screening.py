from typing import List
import os
import uuid
import json
import shutil
import zipfile

from io import BytesIO
from fastapi.responses import StreamingResponse

from database import supabase
from services.extractor import extract_text_from_file
from services.processor import preprocess_text, extract_skills_from_text
from services.matcher import calculate_match_score

from fastapi import Depends, APIRouter, UploadFile, File, Form, HTTPException
from fastapi.security import OAuth2PasswordBearer
from utils.security import verify_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

router = APIRouter()

UPLOAD_BASE = "uploads"

if not os.path.exists(UPLOAD_BASE):
    os.makedirs(UPLOAD_BASE)


# ==============================
# 🔐 AUTH USER
# ==============================

def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


# ==============================
# 🔒 VALIDATE ACTIVE SESSION
# ==============================

def validate_active_session(user_id: str, session_id: str):

    active = supabase.table("active_sessions") \
        .select("session_id") \
        .eq("user_id", user_id) \
        .execute()

    if not active.data:
        raise HTTPException(status_code=403, detail="No active session found")

    if active.data[0]["session_id"] != session_id:
        raise HTTPException(status_code=403, detail="Invalid session")


# ==============================
# 🆕 CREATE SESSION
# ==============================

@router.post("/session")
async def create_session(user_id: str = Depends(get_current_user)):

    # Check existing session
    existing = supabase.table("active_sessions") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    if existing.data:
        old_session_id = existing.data[0]["session_id"]
        old_folder = os.path.join(UPLOAD_BASE, old_session_id)

        if os.path.exists(old_folder):
            shutil.rmtree(old_folder)

        supabase.table("active_sessions") \
            .delete() \
            .eq("user_id", user_id) \
            .execute()

    # Create new session
    session_id = str(uuid.uuid4())
    session_folder = os.path.join(UPLOAD_BASE, session_id)
    os.makedirs(session_folder)

    with open(os.path.join(session_folder, "metadata.json"), "w") as f:
        json.dump({"resumes": []}, f)

    # Store active session
    supabase.table("active_sessions").insert({
        "user_id": user_id,
        "session_id": session_id
    }).execute()

    return {"session_id": session_id}


# ==============================
# 📄 SCREEN RESUMES
# ==============================

@router.post("/session/{session_id}/screen")
async def screen_resumes(
    session_id: str,
    job_description: str = Form(...),
    skills: str = Form(...),
    files: List[UploadFile] = File(...),
    user_id: str = Depends(get_current_user)
):

    validate_active_session(user_id, session_id)

    session_folder = os.path.join(UPLOAD_BASE, session_id)

    if not os.path.exists(session_folder):
        raise HTTPException(status_code=404, detail="Session not found")

    metadata_path = os.path.join(session_folder, "metadata.json")

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    results = []

    for file in files:

        resume_id = str(uuid.uuid4())
        stored_filename = f"{resume_id}_{file.filename}"
        file_path = os.path.join(session_folder, stored_filename)

        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        raw_text = extract_text_from_file(file_path)
        processed_text = preprocess_text(raw_text)
        extracted_skills = extract_skills_from_text(processed_text)

        score, matched = calculate_match_score(
            job_description,
            skills.split(","),
            processed_text,
            extracted_skills
        )

        resume_data = {
            "id": resume_id,
            "filename": file.filename,
            "stored_filename": stored_filename,
            "match_score": int(score),
            "matched_skills": matched,
            "raw_text": raw_text
        }

        metadata["resumes"].append(resume_data)
        results.append(resume_data)

    with open(metadata_path, "w") as f:
        json.dump(metadata, f)

    return {"results": results}


# ==============================
# 📊 DASHBOARD
# ==============================

@router.get("/session/{session_id}/dashboard")
async def dashboard(session_id: str, user_id: str = Depends(get_current_user)):

    validate_active_session(user_id, session_id)

    metadata_path = os.path.join(UPLOAD_BASE, session_id, "metadata.json")

    if not os.path.exists(metadata_path):
        raise HTTPException(status_code=404, detail="Session not found")

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    return metadata["resumes"]


# ==============================
# 📦 DOWNLOAD ALL
# ==============================

@router.get("/session/{session_id}/download-all")
async def download_all(session_id: str, user_id: str = Depends(get_current_user)):

    validate_active_session(user_id, session_id)

    session_folder = os.path.join(UPLOAD_BASE, session_id)

    if not os.path.exists(session_folder):
        raise HTTPException(status_code=404, detail="Session not found")

    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for file in os.listdir(session_folder):
            if file != "metadata.json":
                zf.write(os.path.join(session_folder, file), arcname=file)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=resumes.zip"}
    )


# ==============================
# 🗑 CLEAR SESSION
# ==============================

@router.delete("/session/{session_id}")
async def clear_session(session_id: str, user_id: str = Depends(get_current_user)):

    validate_active_session(user_id, session_id)

    session_folder = os.path.join(UPLOAD_BASE, session_id)

    if os.path.exists(session_folder):
        shutil.rmtree(session_folder)

    supabase.table("active_sessions") \
        .delete() \
        .eq("user_id", user_id) \
        .execute()

    return {"message": "Session cleared"}


# ==============================
# 🚪 LOGOUT
# ==============================

@router.post("/logout")
async def logout(user_id: str = Depends(get_current_user)):

    active = supabase.table("active_sessions") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    if active.data:
        session_id = active.data[0]["session_id"]
        folder = os.path.join(UPLOAD_BASE, session_id)

        if os.path.exists(folder):
            shutil.rmtree(folder)

        supabase.table("active_sessions") \
            .delete() \
            .eq("user_id", user_id) \
            .execute()

    return {"message": "Logged out and session cleared"}