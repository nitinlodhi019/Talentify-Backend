from fastapi import APIRouter, HTTPException
from database import supabase

router = APIRouter()

@router.get("/usage/{user_id}")
async def get_usage(user_id: str):

    response = supabase.table("user_usage") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Usage record not found")

    usage = response.data[0]

    return {
        "resumes_used": usage["resumes_used"],
        "resumes_limit": usage["resumes_limit"]
    }
