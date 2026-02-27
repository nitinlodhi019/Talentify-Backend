from pydantic import BaseModel
from typing import List, Optional

class SignupSchema(BaseModel):
    email: str
    password: str
    phone: Optional[str] = None

class LoginSchema(BaseModel):
    email: str
    password: str

class ScreenRequestSchema(BaseModel):
    user_id: str
    job_description: str
    skills: List[str]
    experience_required: Optional[str] = None
