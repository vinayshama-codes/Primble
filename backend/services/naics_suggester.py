"""Industry-classification (NAICS / SIC) candidate suggestion.

Figure 20 client feedback: the Form Assistant answered "what is a NAICS code?"
well, but generically - and the on-screen hint carried one hard-coded roofing
example for EVERY business, whether they were a roofer or a bakery. The client
asked for examples derived from the DETECTED business, and (engineering note)
for suggested NAICS/SIC candidates carrying a confidence, "clearly marked as
suggestions until confirmed".

Design decisions worth knowing before changing this:

1. **Deterministic retrieval, not an LLM guess.** Candidates come from a
   curated keyword table scored against the business's own operations text.
   A NAICS code drives class assignment and rate; an LLM inventing a
   plausible-looking 6-digit code that nobody can trace is exactly the failure
   this codebase's "blank over wrong" rule exists to prevent. No match means no
   suggestion, which is a safe and honest outcome. It also costs no tokens and
   no latency on a question-generation path that is already expensive.

2. **Suggestions are never answers.** This module only produces candidates.
   Nothing here writes a fact, pre-fills an input, or stamps a form. The client
   must tap a candidate for it to become their answer, and the copy tells them
   to confirm it with their agent.

3. **Confidence is about the MATCH, not about the code.** "high" means the
   business text named this trade distinctly and nothing else scored close.
   It never means "this is certainly the right code for your policy".
"""

from __future__ import annotations

import re
from typing import List, Optional

# Score weights. A "strong" keyword names the trade itself ("roofing"); a
# "weak" one only supports it ("contractor", "repair") and is worthless alone.
_STRONG = 3
_WEAK = 1

# Curated commercial-lines industry table.
#   (label, naics, sic, strong keywords, weak keywords)
# Labels are client-facing: plain English, no jargon, no em-dashes.
_INDUSTRIES: list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = [
    # ── Construction trades ────────────────────────────────────────────────
    ("Roofing contractor", "238160", "1761",
     ("roofing", "roofer", "roofers", "shingle", "shingles", "reroof", "re-roof"),
     ("gutter", "gutters", "siding", "contractor")),
    ("Plumbing, heating and air-conditioning contractor", "238220", "1711",
     ("plumbing", "plumber", "plumbers", "hvac", "heating and air", "air conditioning", "boiler"),
     ("furnace", "ductwork", "pipefitting", "contractor")),
    ("Electrical contractor", "238210", "1731",
     ("electrical contractor", "electrician", "electricians", "wiring", "rewiring"),
     ("electrical", "panel", "voltage", "contractor")),
    ("Painting and wall covering contractor", "238320", "1721",
     ("painting contractor", "painter", "painters", "wallcovering", "wall covering", "repainting"),
     ("painting", "drywall finishing", "contractor")),
    ("Drywall and insulation contractor", "238310", "1742",
     ("drywall", "sheetrock", "insulation contractor", "plastering", "acoustical"),
     ("insulation", "taping", "contractor")),
    ("Framing contractor", "238130", "1751",
     ("framing contractor", "framer", "framers", "wood framing"),
     ("framing", "carpentry", "contractor")),
    ("Finish carpentry contractor", "238350", "1751",
     ("finish carpentry", "cabinet installation", "trim carpentry", "millwork install"),
     ("carpentry", "carpenter", "cabinetry", "contractor")),
    ("Masonry contractor", "238140", "1741",
     ("masonry", "mason", "bricklaying", "bricklayer", "stonework", "stucco"),
     ("brick", "block", "contractor")),
    ("Concrete contractor", "238110", "1771",
     ("concrete contractor", "poured concrete", "concrete foundation", "flatwork"),
     ("concrete", "foundation", "rebar", "contractor")),
    ("Flooring contractor", "238330", "1752",
     ("flooring", "carpet installation", "tile installation", "hardwood floor"),
     ("floor", "tile", "carpet", "contractor")),
    ("Glass and glazing contractor", "238150", "1793",
     ("glazing", "glazier", "glass installation", "storefront glass"),
     ("glass", "window install", "contractor")),
    ("Excavation contractor", "238910", "1794",
     ("excavation", "excavating", "grading contractor", "site preparation", "earthmoving"),
     ("backhoe", "trenching", "demolition", "contractor")),
    ("Landscaping services", "561730", "0782",
     ("landscaping", "landscaper", "lawn care", "lawn maintenance", "tree trimming", "arborist"),
     ("mowing", "irrigation", "groundskeeping")),
    ("Residential building construction", "236115", "1521",
     ("home builder", "homebuilder", "residential construction", "custom homes", "house building"),
     ("residential", "single family", "construction")),
    ("Commercial building construction", "236220", "1542",
     ("commercial construction", "commercial building", "office building construction"),
     ("commercial", "construction", "build-out")),
    ("General contractor (construction management)", "236118", "1531",
     ("general contractor", "remodeling", "remodeler", "renovation contractor", "construction management"),
     ("remodel", "renovation", "contractor", "construction")),
    ("Septic, water well and utility line contractor", "237110", "1781",
     ("water well", "septic system", "utility line", "sewer line", "pipeline construction"),
     ("septic", "drilling", "contractor")),
    ("Highway, street and bridge construction", "237310", "1611",
     ("highway construction", "road construction", "paving contractor", "asphalt paving", "bridge construction"),
     ("paving", "asphalt", "roadway")),

    # ── Manufacturing ──────────────────────────────────────────────────────
    ("Machine shop", "332710", "3599",
     ("machine shop", "machining", "cnc machining", "precision machining"),
     ("lathe", "milling", "fabrication")),
    ("Metal fabrication", "332312", "3441",
     ("metal fabrication", "structural steel", "steel fabrication", "welding shop"),
     ("welding", "metalwork", "fabrication")),
    ("Plastics product manufacturing", "326199", "3089",
     ("plastic manufacturing", "injection molding", "plastics manufacturer"),
     ("plastic", "molding", "extrusion")),
    ("Food manufacturing", "311999", "2099",
     ("food manufacturing", "food processing", "food production plant"),
     ("food", "packaging", "processing")),
    ("Bakery, commercial", "311812", "2051",
     ("commercial bakery", "wholesale bakery", "bread manufacturing"),
     ("bakery", "baking", "pastry")),
    ("Wood product manufacturing", "321999", "2499",
     ("woodworking", "wood products manufacturing", "cabinet manufacturing", "millwork manufacturing"),
     ("lumber", "wood", "sawmill")),
    ("Printing services", "323111", "2752",
     ("commercial printing", "printing company", "print shop", "screen printing"),
     ("printing", "lithographic", "signage")),

    # ── Wholesale / retail ─────────────────────────────────────────────────
    ("Building material and supplies dealer", "444180", "5211",
     ("building materials", "lumber yard", "hardware store", "building supply"),
     ("supply", "materials", "wholesale")),
    ("Grocery store", "445110", "5411",
     ("grocery store", "supermarket", "grocer"),
     ("grocery", "market", "food retail")),
    ("Convenience store", "445131", "5412",
     ("convenience store", "corner store", "c-store"),
     ("convenience", "gas station")),
    ("Clothing and accessories retail", "458110", "5651",
     ("clothing store", "apparel retail", "boutique"),
     ("clothing", "apparel", "retail")),
    ("Restaurant, full-service", "722511", "5812",
     ("full service restaurant", "fine dining", "sit-down restaurant", "restaurant"),
     ("dining", "kitchen", "menu", "food service")),
    ("Restaurant, limited-service", "722513", "5812",
     ("fast food", "quick service restaurant", "limited service restaurant", "takeout restaurant"),
     ("counter service", "drive-thru", "food service")),
    ("Bar or drinking establishment", "722410", "5813",
     ("bar", "tavern", "nightclub", "brewpub", "cocktail lounge"),
     ("alcohol", "liquor", "drinking")),
    ("Caterer", "722320", "5812",
     ("catering", "caterer", "catered events"),
     ("banquet", "event food")),
    ("Motor vehicle parts retail", "441330", "5531",
     ("auto parts store", "automotive parts retail"),
     ("auto parts", "parts", "retail")),

    # ── Auto / transport ───────────────────────────────────────────────────
    ("Automotive repair and maintenance", "811111", "7538",
     ("auto repair", "automotive repair", "mechanic shop", "repair garage", "auto service"),
     ("automotive", "mechanic", "brakes", "oil change")),
    ("Automotive body and paint shop", "811121", "7532",
     ("body shop", "collision repair", "auto body", "auto painting"),
     ("collision", "bodywork", "refinishing")),
    ("General freight trucking, long-distance", "484121", "4213",
     ("long haul trucking", "long-distance trucking", "interstate trucking", "over the road"),
     ("trucking", "freight", "hauling", "carrier")),
    ("General freight trucking, local", "484110", "4212",
     ("local trucking", "local delivery", "short haul", "local hauling"),
     ("trucking", "delivery", "freight")),
    ("Courier and express delivery", "492110", "4215",
     ("courier", "express delivery", "parcel delivery", "last mile delivery"),
     ("delivery", "dispatch")),
    ("Taxi and limousine service", "485320", "4119",
     ("limousine", "taxi service", "black car service", "chauffeur"),
     ("livery", "passenger transport")),

    # ── Professional / office ──────────────────────────────────────────────
    ("Offices of lawyers", "541110", "8111",
     ("law firm", "attorney", "attorneys", "legal practice", "law office"),
     ("legal", "litigation", "counsel")),
    ("Accounting and bookkeeping services", "541219", "8721",
     ("accounting firm", "bookkeeping", "cpa firm", "tax preparation"),
     ("accounting", "payroll services", "audit")),
    ("Architectural services", "541310", "8712",
     ("architectural services", "architect", "architecture firm"),
     ("design", "drafting", "plans")),
    ("Engineering services", "541330", "8711",
     ("engineering services", "engineering firm", "structural engineering", "civil engineering"),
     ("engineering", "engineer", "design")),
    ("Computer systems design and IT services", "541512", "7371",
     ("software development", "it services", "systems design", "software company", "web development"),
     ("software", "technology", "programming", "saas")),
    ("Management consulting services", "541611", "8742",
     ("management consulting", "business consulting", "consulting firm"),
     ("consulting", "consultant", "advisory")),
    ("Insurance agency or brokerage", "524210", "6411",
     ("insurance agency", "insurance brokerage", "insurance broker", "insurance agent"),
     ("insurance", "brokerage", "underwriting")),
    ("Real estate property management", "531311", "6531",
     ("property management", "property manager", "rental management"),
     ("real estate", "leasing", "tenants")),
    ("Real estate agency", "531210", "6531",
     ("real estate agency", "real estate brokerage", "realtor"),
     ("real estate", "listings", "brokerage")),
    ("Advertising agency", "541810", "7311",
     ("advertising agency", "marketing agency", "ad agency"),
     ("advertising", "marketing", "creative")),

    # ── Health / personal / other services ─────────────────────────────────
    ("Offices of physicians", "621111", "8011",
     ("medical practice", "physician office", "doctors office", "clinic"),
     ("medical", "physician", "patients")),
    ("Offices of dentists", "621210", "8021",
     ("dental practice", "dentist", "dental office", "orthodontic"),
     ("dental", "hygienist")),
    ("Child day care services", "624410", "8351",
     ("day care", "daycare", "child care center", "preschool", "nursery school"),
     ("children", "childcare")),
    ("Fitness and recreational sports center", "713940", "7991",
     ("gym", "fitness center", "health club", "yoga studio", "crossfit"),
     ("fitness", "exercise", "training studio")),
    ("Beauty salon", "812112", "7231",
     ("hair salon", "beauty salon", "barbershop", "barber shop", "nail salon"),
     ("salon", "stylist", "cosmetology")),
    ("Janitorial services", "561720", "7349",
     ("janitorial", "commercial cleaning", "custodial services", "office cleaning"),
     ("cleaning", "housekeeping", "sanitation")),
    ("Security guard services", "561612", "7381",
     ("security guard", "security services", "armed guard", "patrol services"),
     ("security", "guard", "surveillance")),
    ("Temporary help / staffing services", "561320", "7363",
     ("staffing agency", "temporary staffing", "temp agency", "employment agency"),
     ("staffing", "recruiting", "placement")),
    ("Warehousing and storage", "493110", "4225",
     ("warehousing", "warehouse storage", "distribution center", "self storage"),
     ("warehouse", "storage", "distribution")),
    ("Hotel or motel", "721110", "7011",
     ("hotel", "motel", "inn", "lodging", "bed and breakfast"),
     ("hospitality", "guest rooms")),
    ("Farming, crop production", "111998", "0191",
     ("crop farming", "farming operation", "grain farming", "orchard", "vineyard"),
     ("farm", "agriculture", "harvest")),
]

# Fields whose answer is an industry classification code. Keyed by the canonical
# fact key; `field_name` is checked against the same set.
NAICS_KEYS = frozenset({"naics_code"})
SIC_KEYS = frozenset({"sic_code"})

_MAX_SUGGESTIONS = 3
_MAX_TEXT = 4000

# Generic terms that describe a legal wrapper, not an industry. Left out of the
# scored text so "Acme Construction LLC" is not read as a match for "LLC".
_STOP = re.compile(
    r"\b(?:llc|l\.l\.c|inc|incorporated|corp|corporation|co|company|ltd|limited|"
    r"lp|llp|plc|pllc|dba|the|and|of)\b",
    re.I,
)
_NON_WORD = re.compile(r"[^a-z0-9]+")

# Negation cues. An insurance application describes a risk as much by what it
# EXCLUDES as by what it does ("there is no nightclub", "no manufacturing is
# performed", "no vehicles are owned"), and a plain keyword match reads those
# excluded nouns as evidence FOR the thing being excluded. Observed live: a
# full-service restaurant picked up a "Bar or drinking establishment" candidate
# purely from the sentence disclaiming a nightclub.
_NEGATION_CUES = frozenset({
    "no", "not", "none", "never", "without", "excluding", "excluded",
    "excludes", "exclude", "neither", "nor", "cannot", "wont", "doesnt",
    "dont", "isnt", "arent", "havent", "hasnt",
})
# How far into a clause a cue may sit and still negate the whole clause.
# "There is no nightclub" puts the cue at index 2; beyond a short prefix the cue
# is more likely qualifying a detail than the clause's subject.
_NEGATION_WINDOW = 4
# Clause boundaries. Deliberately NOT splitting on "and": that would sever real
# multi-word trades like "heating and air conditioning".
_CLAUSE_SPLIT = re.compile(r"[,.;:!?\n\r]+")


def _strip_negated_clauses(text: str) -> str:
    """Drop clauses whose subject is negated, before any keyword scoring.

    Clause-level rather than sentence-level, because these disclaimers stack
    inside one sentence ("There is no nightclub, no dance floor, and no live
    entertainment") and a sentence-level rule would either keep all three or
    throw away a neighbouring positive clause.

    Conservative by construction: it only ever REMOVES text, so it can cost a
    match but can never invent one, and a wrongly-dropped clause degrades to
    "no suggestion" - the safe direction for this feature.
    """
    if not text:
        return ""
    kept = []
    for clause in _CLAUSE_SPLIT.split(str(text)):
        tokens = _NON_WORD.sub(" ", clause.lower()).split()
        if any(t in _NEGATION_CUES for t in tokens[:_NEGATION_WINDOW]):
            continue
        kept.append(clause)
    return ". ".join(kept)


def _normalize(text: str) -> str:
    """Lowercase, strip legal-entity noise, collapse to space-delimited words.

    Keeps a leading and trailing space so `" roofing "` style word-boundary
    checks are a plain substring test - meaningfully faster than compiling a
    regex per keyword, and there are several hundred keywords.
    """
    if not text:
        return ""
    low = _NON_WORD.sub(" ", str(text)[:_MAX_TEXT].lower())
    low = _STOP.sub(" ", low)
    return " " + re.sub(r"\s+", " ", low).strip() + " "


def _hits(haystack: str, keywords: tuple[str, ...]) -> int:
    """Count distinct keywords present as whole words/phrases."""
    n = 0
    for kw in keywords:
        needle = _NON_WORD.sub(" ", kw.lower()).strip()
        if needle and f" {needle} " in haystack:
            n += 1
    return n


def suggest(business_text: str) -> List[dict]:
    """Rank industry candidates for a free-text business description.

    Returns up to 3 dicts:
        {"label", "naics", "sic", "confidence": high|medium|low}
    Empty list when nothing matched - callers must treat that as "no
    suggestion", never as "unknown industry, guess something".
    """
    hay = _normalize(_strip_negated_clauses(business_text))
    if not hay.strip():
        return []

    scored = []
    for label, naics, sic, strong, weak in _INDUSTRIES:
        s_hits = _hits(hay, strong)
        w_hits = _hits(hay, weak)
        score = s_hits * _STRONG + w_hits * _WEAK
        if score > 0:
            scored.append((score, s_hits, label, naics, sic))

    if not scored:
        return []

    # Sort by score, then by strong-keyword count (a distinct trade name beats a
    # pile of generic supporting words), then by label for stable ordering.
    scored.sort(key=lambda r: (-r[0], -r[1], r[2]))
    top_score = scored[0][0]
    runner_up = scored[1][0] if len(scored) > 1 else 0

    out = []
    for score, s_hits, label, naics, sic in scored[:_MAX_SUGGESTIONS]:
        if s_hits and score == top_score and score >= _STRONG and score >= runner_up * 2:
            confidence = "high"
        elif s_hits:
            confidence = "medium"
        else:
            # Only generic supporting words matched. Real enough to show, far
            # too weak to imply it is probably right.
            confidence = "low"
        out.append({
            "label": label,
            "naics": naics,
            "sic": sic,
            "confidence": confidence,
        })

    # When one candidate is a clear match, drop the weak also-rans. A roofer's
    # operations text incidentally contains "commercial" and "asphalt", which
    # scrape up low-confidence construction entries; showing them next to a
    # correct "high" candidate adds no information and gives the client a way to
    # tap the wrong code. Medium candidates survive - those are real
    # alternatives worth a look.
    if any(s["confidence"] == "high" for s in out):
        out = [s for s in out if s["confidence"] != "low"]
    return out


def business_text_from_facts(facts: dict, fact_value=None) -> str:
    """Assemble the description this module scores, from extracted facts.

    `fact_value` is the caller's fact-envelope unwrapper (`extraction_service._fv`);
    passing it in keeps this module free of a circular import and trivially
    testable with a plain dict.
    """
    if not isinstance(facts, dict):
        return ""

    def _get(key: str) -> str:
        try:
            v = fact_value(facts, key) if fact_value else facts.get(key)
        except Exception:
            v = None
        if isinstance(v, dict) and "value" in v:
            v = v.get("value")
        return str(v).strip() if v not in (None, "") else ""

    # Ordered most- to least-descriptive. Operations text is the real signal;
    # the business name is a weak but genuinely useful tiebreaker ("Statewide
    # Roofing LLC"), and the certificate/WC operations blurbs often carry the
    # trade wording when the applicant left the main description thin.
    parts = [
        _get("operations_description"),
        _get("certificate_description_of_operations"),
        _get("wc_description_of_operations"),
        _get("applicant_name"),
        _get("dba_name"),
    ]
    return " ".join(p for p in parts if p)[:_MAX_TEXT]


def _confidence_phrase(confidence: str) -> str:
    return {
        "high": "likely",
        "medium": "possible",
        "low": "rough",
    }.get(confidence, "possible")


def hint_for(kind: str, suggestions: List[dict], fallback: str = "") -> Optional[str]:
    """Business-specific on-screen hint, or None to keep the existing one.

    `kind` is "naics" or "sic". Copy rules: plain hyphens only (no em-dashes),
    and it must always restate that leaving the box blank is fine - that is the
    part of the current experience the client explicitly praised.
    """
    if not suggestions:
        return None
    top = suggestions[0]
    code = top["naics"] if kind == "naics" else top["sic"]
    if not code:
        return None
    width = "6-digit" if kind == "naics" else "4-digit"
    older = "" if kind == "naics" else " older"
    return (
        f"This is a {width}{older} industry code. Based on what your business does, a "
        f"{_confidence_phrase(top['confidence'])} match is '{code}' ({top['label']}). "
        "Treat that as a suggestion to confirm with your agent, not a confirmed answer - "
        "and leave the box blank if you are unsure."
    )


def suggestions_for(kind: str, business_text: str) -> List[dict]:
    """Client-facing candidate list for one code type.

    Shaped for the questionnaire renderer: `code` is already the right code for
    `kind`, so the UI never has to know which key to read.
    """
    out = []
    for s in suggest(business_text):
        code = s["naics"] if kind == "naics" else s["sic"]
        if not code:
            continue
        out.append({
            "code": code,
            "label": s["label"],
            "confidence": s["confidence"],
        })
    return out
