from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from session_store import cleanup_old_sessions
from routers import auth, screening

app = FastAPI(title="AI Resume Screener API")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(screening.router, prefix="/api")


@app.on_event("startup")
async def on_startup():
    cleanup_old_sessions()


@app.get("/")
def root():
    return {"message": "AI Resume Screener Backend Running 🚀"}


@app.get("/success")
def email_verified_success():
    return "✅ Email verified successfully. You can now return to your app and login."