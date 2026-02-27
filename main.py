from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import time

from routers import auth, screening

app = FastAPI()

# ==========================
# 🌍 CORS CONFIG
# ==========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Change to frontend URL later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# 📌 REGISTER ROUTERS
# ==========================

app.include_router(auth.router, prefix="/api")
app.include_router(screening.router, prefix="/api")

# ==========================
# 🧹 CLEANUP OLD SESSIONS
# ==========================

UPLOAD_BASE = "uploads"

@app.on_event("startup")
async def cleanup_old_sessions():
    if not os.path.exists(UPLOAD_BASE):
        return

    for folder in os.listdir(UPLOAD_BASE):
        folder_path = os.path.join(UPLOAD_BASE, folder)

        if os.path.isdir(folder_path):
            created_time = os.path.getctime(folder_path)
            # delete if older than 1 hour
            if time.time() - created_time > 3600:
                shutil.rmtree(folder_path)

# ==========================
# ROOT ROUTE
# ==========================

@app.get("/")
def root():
    return {"message": "AI Resume Screener Backend Running 🚀"}