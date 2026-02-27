from fastapi import APIRouter, HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from database import supabase
from schemas import SignupSchema, LoginSchema
from utils.security import create_access_token

router = APIRouter()

@router.post("/signup")
async def signup(data: SignupSchema):

    existing = supabase.table("users") \
        .select("*") \
        .eq("email", data.email) \
        .execute()

    if existing.data:
        raise HTTPException(status_code=400, detail="User already exists")

    hashed = generate_password_hash(data.password)

    response = supabase.table("users").insert({
        "email": data.email,
        "phone": data.phone,
        "password_hash": hashed,
        "is_verified": True
    }).execute()

    user_id = response.data[0]["id"]

    # Initialize usage
    supabase.table("user_usage").insert({
        "user_id": user_id,
        "resumes_used": 0,
        "resumes_limit": 50
    }).execute()

    return {"message": "User created", "user_id": user_id}

@router.post("/login")
async def login(data: LoginSchema):

    response = supabase.table("users") \
        .select("*") \
        .eq("email", data.email) \
        .execute()

    if not response.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = response.data[0]

    if not check_password_hash(user["password_hash"], data.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token({
        "user_id": user["id"]
    })

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer"
    }