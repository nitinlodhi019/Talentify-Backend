"""
routers/auth.py
All authentication endpoints – ported from Flask to FastAPI.
Supabase interaction is identical to the original.
"""

import os
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

router = APIRouter()

# ── Supabase client ──────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://localhost:8000")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "dummy_key")

if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
    print("WARNING: SUPABASE_URL / SUPABASE_KEY not set. Supabase features will not work.")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Could not connect to Supabase: {e}. Supabase features will be disabled.")
    supabase = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def generate_otp() -> str:
    return str(random.randint(100000, 999999))


def send_otp_email(to_email: str, otp: str) -> None:
    sender_email = os.environ.get("SMTP_USER", "")
    sender_pass = os.environ.get("SMTP_PASS", "")

    if not sender_email or not sender_pass:
        print("SMTP_USER or SMTP_PASS not set. Email sending skipped.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔐 Your OTP for Resume Screening Verification"
    msg["From"] = sender_email
    msg["To"] = to_email

    text = (
        f"Hi,\n\nYour OTP for Resume Screening verification is: {otp}\n\n"
        "This OTP is valid for 10 minutes. Do not share it with anyone.\n\n"
        "If you did not request this, please ignore this email.\n\nThanks,\nResume Screening Team"
    )

    html = f"""
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px;">
    <div style="max-width:600px;margin:auto;background:#fff;border-radius:8px;padding:30px;
                box-shadow:0 0 10px rgba(0,0,0,.1);">
      <h2 style="color:#2e86de;">🔐 Resume Screening OTP Verification</h2>
      <p>Hi there,</p>
      <p>Your One-Time Password (OTP) for verifying your email address is:</p>
      <h1 style="color:#27ae60;letter-spacing:4px;">{otp}</h1>
      <p>This OTP is valid for <strong>10 minutes</strong>. Please do not share it with anyone.</p>
      <hr style="margin:30px 0;">
      <p style="font-size:.9em;color:#888;">
        If you did not request this email, you can safely ignore it.<br>
        Need help? Contact us at
        <a href="mailto:nitin.renusharmafoundation@gmail.com">nitin.renusharmafoundation@gmail.com</a>
      </p>
      <p style="font-size:.9em;color:#888;">Thanks,<br>The Resume Screening Team</p>
    </div>
  </body>
</html>"""

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        print(f"✅ OTP sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send OTP email to {to_email}: {e}")


# ── Request schemas ───────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str
    phone: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class VerifyOtpRequest(BaseModel):
    email: str
    otp: str
    action: str = "signup"


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    new_password: str


class SelectRoleRequest(BaseModel):
    email: str
    role: str | None = None
    full_name: str | None = None
    hr_id: str | None = None
    position: str | None = None
    department: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/signup")
def signup(body: SignupRequest):
    if not supabase:
        return JSONResponse({"message": "Database not connected. Signup is unavailable."}, 500)

    try:
        resp = supabase.table("users").select("id", "is_verified").eq("email", body.email).execute()
        existing = resp.data[0] if resp.data else None

        if existing:
            if existing.get("is_verified"):
                return JSONResponse({"message": "User with this email already exists and is verified."}, 409)
            # Not verified – resend OTP
            otp = generate_otp()
            supabase.table("users").update({"otp": otp}).eq("email", body.email).execute()
            send_otp_email(body.email, otp)
            return JSONResponse(
                {"message": "User exists but not verified. OTP resent.", "user_id": existing["id"]}, 200
            )

        hashed = generate_password_hash(body.password)
        otp = generate_otp()

        resp = supabase.table("users").insert({
            "email": body.email,
            "phone": body.phone,
            "password_hash": hashed,
            "otp": otp,
            "is_verified": False,
        }).execute()

        if resp.data:
            user_id = resp.data[0]["id"]
            # Create usage tracking row for new user
            supabase.table("user_usage").insert({
                "user_id": user_id,
                "resumes_used": 0,
                "resumes_limit": 50,
            }).execute()
            send_otp_email(body.email, otp)
            return JSONResponse(
                {"message": "User registered successfully. OTP sent for email verification.", "user_id": user_id}, 201
            )
        return JSONResponse({"message": "Failed to register user."}, 500)

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"message": f"An error occurred during signup: {e}"}, 500)


@router.post("/login")
def login(body: LoginRequest):
    if not supabase:
        return JSONResponse({"message": "Database not connected. Login is unavailable."}, 500)

    try:
        resp = supabase.table("users").select("*").eq("email", body.email).execute()
        user = resp.data[0] if resp.data else None

        if not user or not check_password_hash(user["password_hash"], body.password):
            return JSONResponse({"message": "Invalid email or password"}, 401)

        if not user.get("is_verified"):
            return JSONResponse({"message": "Please verify your email via OTP first."}, 403)

        supabase.table("users").update({"otp": None}).eq("email", body.email).execute()

        return JSONResponse({
            "message": "Login successful",
            "user_id": user["id"],
            "role_set": user.get("role") is not None,
            "email": user["email"],
            "name": user.get("full_name") or user["email"].split("@")[0],
            "role": user.get("role"),
            "department": user.get("department"),
            "position": user.get("position"),
        }, 200)

    except Exception as e:
        return JSONResponse({"message": f"An error occurred during login: {e}"}, 500)


@router.post("/verify_otp")
def verify_otp(body: VerifyOtpRequest):
    if not supabase:
        return JSONResponse({"message": "Database not connected. OTP verification is unavailable."}, 500)

    try:
        resp = supabase.table("users").select(
            "id", "otp", "is_verified", "role", "full_name", "department", "position"
        ).eq("email", body.email).execute()
        user = resp.data[0] if resp.data else None

        if not user or user["otp"] != body.otp:
            return JSONResponse({"message": "Invalid OTP"}, 401)

        update_data: dict = {"otp": None}
        if body.action == "signup":
            update_data["is_verified"] = True

        supabase.table("users").update(update_data).eq("email", body.email).execute()

        if body.action == "signup":
            return JSONResponse({
                "message": "Email verified and login successful",
                "user_id": user["id"],
                "role_set": user.get("role") is not None,
                "email": body.email,
                "name": user.get("full_name") or body.email.split("@")[0],
                "role": user.get("role"),
                "department": user.get("department"),
                "position": user.get("position"),
            }, 200)

        if body.action == "reset_password":
            return JSONResponse(
                {"message": "OTP verified. You can now reset your password.", "user_id": user["id"]}, 200
            )

        return JSONResponse({"message": "Invalid action for OTP verification"}, 400)

    except Exception as e:
        return JSONResponse({"message": f"An error occurred during OTP verification: {e}"}, 500)


@router.post("/forgot_password")
def forgot_password(body: ForgotPasswordRequest):
    if not supabase:
        return JSONResponse({"message": "Database not connected. Forgot password is unavailable."}, 500)

    try:
        resp = supabase.table("users").select("id").eq("email", body.email).execute()
        if not resp.data:
            return JSONResponse({"message": "User not found"}, 404)

        otp = generate_otp()
        supabase.table("users").update({"otp": otp}).eq("email", body.email).execute()
        send_otp_email(body.email, otp)
        print(f"Demo OTP for password reset for {body.email}: {otp}")
        return JSONResponse({"message": "OTP sent to your email for password reset"}, 200)

    except Exception as e:
        return JSONResponse({"message": f"An error occurred during forgot password: {e}"}, 500)


@router.post("/reset_password")
def reset_password(body: ResetPasswordRequest):
    if not supabase:
        return JSONResponse({"message": "Database not connected. Password reset is unavailable."}, 500)

    try:
        resp = supabase.table("users").select("id").eq("email", body.email).execute()
        if not resp.data:
            return JSONResponse({"message": "User not found"}, 404)

        hashed = generate_password_hash(body.new_password)
        supabase.table("users").update({"password_hash": hashed, "otp": None}).eq("email", body.email).execute()
        return JSONResponse({"message": "Password reset successfully"}, 200)

    except Exception as e:
        return JSONResponse({"message": f"An error occurred during password reset: {e}"}, 500)


@router.post("/select_role")
@router.put("/select_role")
def select_role(body: SelectRoleRequest):
    if not body.email:
        return JSONResponse({"message": "Email is required"}, 400)

    if not supabase:
        return JSONResponse({"message": "Database not connected. Role selection is unavailable."}, 500)

    try:
        resp = supabase.table("users").update({
            "role": body.role,
            "full_name": body.full_name,
            "position": body.position,
            "department": body.department,
        }).eq("email", body.email).execute()

        if resp.data:
            return JSONResponse({"message": f"Role '{body.role}' and HR info updated for {body.email}"}, 200)
        return JSONResponse({"message": "User not found or failed to update"}, 404)

    except Exception as e:
        return JSONResponse({"message": f"An error occurred during role selection: {e}"}, 500)