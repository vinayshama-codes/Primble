from pydantic import BaseModel, EmailStr
from typing import Dict, List, Optional


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    organization_name: str
    acord_disclaimer_accepted: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str


class GoogleAuthRequest(BaseModel):
    credential: str


class FormSelectionRequest(BaseModel):
    session_id: str
    selected_form_id: str


class BulkFormSelectionRequest(BaseModel):
    session_id: str
    form_ids: List[str]


class PDFUpdateRequest(BaseModel):
    session_id: str
    field_updates: Dict[str, str]


class CheckoutRequest(BaseModel):
    plan: str = "essentials"
    billing_cycle: str = "monthly"


class OverageCheckoutRequest(BaseModel):
    quantity: int


class ApplyOverageRequest(BaseModel):
    stripe_session_id: str
    qty: int


class SaveSignatureRequest(BaseModel):
    session_id: Optional[str] = None
    signature_data: str


class CompleteProfileRequest(BaseModel):
    organization_name: str
    acord_disclaimer_accepted: bool = False