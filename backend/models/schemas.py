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


from typing import Optional


class RiskTransferFlags(BaseModel):
    """Mirrors the risk_transfer sub-object returned by the extraction prompt."""
    additional_insured_required: bool = False
    additional_insured_names: List[str] = []
    primary_noncontributory_required: bool = False
    waiver_of_subrogation_required: bool = False
    certificate_holder_name: Optional[str] = None
    loss_payee_name: Optional[str] = None
    mortgagee_name: Optional[str] = None
    specific_wording_requirements: Optional[str] = None


class ComplianceCheckItem(BaseModel):
    """One item in the compliance_checklist returned inside the SQS payload."""
    check: str
    label: str
    status: str          # "required" | "advisory" | "info"
    message: str
    advisory: Optional[str] = None


class SaveSignatureRequest(BaseModel):
    signature_data: Optional[str] = None


class CompleteProfileRequest(BaseModel):
    organization_name: str
    acord_disclaimer_accepted: bool = False