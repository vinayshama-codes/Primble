"""
pipeline_router.py
------------------
Single source of truth for which pipeline a tier runs.

CLARITY  — SQS + ARQ + summary. No ACORD form generation. Cheaper to run.
ASSEMBLY — Full ACORD form generation + SQS + ARQ + summary. Current default.

Usage
-----
    from services.pipeline_router import get_pipeline, ProductLine

    pipeline = get_pipeline(current_user["subscription_tier"])
    if pipeline == ProductLine.CLARITY:
        ...  # run facts-based path
    else:
        ...  # run full form generation path

Rules
-----
- Every tier check in the codebase must go through this module.
- Never match tier strings directly in route handlers or service code.
- If a new tier is added, update _TIER_MAP here only.
"""

from enum import Enum


class ProductLine(Enum):
    CLARITY  = "clarity"
    ASSEMBLY = "assembly"


# Canonical mapping: tier name (lower-cased) → pipeline
# Add new tiers here and nowhere else.
_TIER_MAP: dict[str, ProductLine] = {
    # Current tiers
    "lite":         ProductLine.CLARITY,
    "free":         ProductLine.CLARITY,
    # Assembly tiers (current + future names)
    "essentials":   ProductLine.ASSEMBLY,
    "professional": ProductLine.ASSEMBLY,
    "enterprise":   ProductLine.ASSEMBLY,
    # Future Clarity product line
    "clarity":      ProductLine.CLARITY,
    "clarity_pro":  ProductLine.CLARITY,
    "clarity_scale":ProductLine.CLARITY,
    # Future Assembly product line
    "assembly":     ProductLine.ASSEMBLY,
    "assembly_pro": ProductLine.ASSEMBLY,
    "assembly_scale":ProductLine.ASSEMBLY,
}


def get_pipeline(tier_name: str) -> ProductLine:
    """
    Return the ProductLine for a given subscription tier name.
    Defaults to ASSEMBLY for any unrecognised tier so existing
    behaviour is never silently broken.
    """
    if not tier_name:
        return ProductLine.ASSEMBLY
    return _TIER_MAP.get(tier_name.lower().strip(), ProductLine.ASSEMBLY)


def is_clarity(tier_name: str) -> bool:
    return get_pipeline(tier_name) == ProductLine.CLARITY


def is_assembly(tier_name: str) -> bool:
    return get_pipeline(tier_name) == ProductLine.ASSEMBLY
