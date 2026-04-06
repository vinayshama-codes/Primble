import re
from typing import Tuple, List

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","VI","GU","MP","AS",
}

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com","yahoo.com","hotmail.com","outlook.com","icloud.com",
    "live.com","aol.com","msn.com","ymail.com","mail.com",
    "protonmail.com","proton.me","tutanota.com","zoho.com",
}


def validate_work_email(email: str) -> Tuple[bool, str]:
    domain = email.lower().split("@")[-1] if "@" in email else ""
    if domain in PERSONAL_EMAIL_DOMAINS:
        return False, f"Please use a work email. Personal domains ({domain}) are not accepted."
    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    return True, ""


def validate_address(addr: str) -> Tuple[bool, str]:
    if not addr:
        return True, ""
    parts       = addr.upper().split()
    state_found = any(p.strip(",.") in US_STATES for p in parts)
    zip_found   = bool(re.search(r"\b\d{5}(-\d{4})?\b", addr))
    if not state_found:
        return False, f"Address missing valid US state: '{addr}'"
    if not zip_found:
        return False, f"Address missing ZIP code: '{addr}'"
    return True, ""


def validate_phone(phone: str) -> Tuple[bool, str]:
    if not phone:
        return True, ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) not in (10, 11):
        return False, f"Phone '{phone}' should be 10 digits"
    return True, ""


def validate_email_format(email: str) -> Tuple[bool, str]:
    if not email:
        return True, ""
    if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email.strip()):
        return False, f"Email '{email}' is invalid"
    return True, ""


def run_field_validations(facts: dict) -> Tuple[List[str], List[str]]:
    hard, soft = [], []
    for fn, fv in [
        ("mailing_address", validate_address),
        ("contact_phone",   validate_phone),
        ("contact_email",   validate_email_format),
    ]:
        ok, msg = fv(facts.get(fn, ""))
        if not ok:
            soft.append(msg)
    eff = facts.get("effective_date", "")
    exp = facts.get("expiration_date", "")
    if eff and exp:
        fmts = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"]
        from datetime import datetime
        def parse(d):
            for fmt in fmts:
                try:
                    return datetime.strptime(d.strip(), fmt)
                except ValueError:
                    pass
            return None
        d_e, d_x = parse(eff), parse(exp)
        if d_e and d_x and d_e >= d_x:
            hard.append("Effective date is on or after expiration date")
    return hard, soft