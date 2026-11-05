"""Build Primble's search list of ASG's ACORD forms (3 Nov 2026, Accommodate800forms.md D-ASG-2).

Input : ASG's "Supported ACORD forms" PDF (saved from the ASG portal; kept outside git in ASG_DOCUMENTATION/).
Output: backend/forms_catalog/asg_forms_index.json - TEXT ONLY: one entry per form + state version with its
        number, state, suffix, newest listed title and edition. No form is downloaded or stored.

    py backend/scripts/build_asg_forms_index.py "ASG_DOCUMENTATION/SUPPORTED-ACORD-FORMS-ASG.pdf"

    py backend/scripts/build_asg_forms_index.py "ASG_DOCUMENTATION/Prod-forms-download-catalogue.json"   (4 Nov 2026 on)
The JSON is ASG's real DOWNLOAD catalogue (the portal's Forms tab) and is the source since 4 Nov 2026 - the PDF lists
forms Transcriber can READ, not what can be downloaded (308 of its forms could not be). Re-run whenever ASG publishes a new list. Editions in this list are for SEARCH only - generation always asks
ASG for the latest edition and keeps the one it returns.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "forms_catalog", "asg_forms_index.json")

# "137", "137_CA", "137_FL_INS", "137_PA INS", "130_FL_IS"
_NAME_RE = re.compile(r"^(\d{1,4})(?:_([A-Z]{2}))?(?:[_ ]([A-Z]{1,4}))?$")
_ED_FULL = re.compile(r"^(\d{4})/(\d{2})$")
# Two letters after the number are ASG's geo code ONLY when they are a US state / territory. Other pairs
# ("126_GL", "25_FR", "60_US", "130_IS" ...) are variants whose download parameters are unknown; they are left
# out rather than fetched with a guessed geoCode (review 3 Nov 2026) - listed in `skipped_variants`. The
# catalogue build (4 Nov 2026) keeps them as VARIANTS instead, requested with ASG's own code (`_row_identity`).
_GEO_CODES = frozenset("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ
NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR VI GU AS MP""".split())
_ED_SHORT = re.compile(r"^(\d{1,2})/(\d{2})")          # "07/98", "8/88 a"


def edition_key(edition: str) -> str:
    """Sortable YYYY/MM for the editions ASG prints in two shapes."""
    e = (edition or "").strip()
    m = _ED_FULL.match(e)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = _ED_SHORT.match(e)
    if m:
        yy = int(m.group(2))
        return f"{1900 + yy if yy > 30 else 2000 + yy}/{int(m.group(1)):02d}"
    m = re.match(r"^([A-Za-z]{3})-(\d{2})$", e)       # ASG's "Oct-97" (review, 4 Nov 2026)
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    if m and m.group(1).upper() in months:
        yy = int(m.group(2))
        return f"{1900 + yy if yy > 30 else 2000 + yy}/{months.index(m.group(1).upper()) + 1:02d}"
    return "0000/00"


def form_id_for(number: str, state: str, suffix: str) -> str:
    return "ACORD_" + "_".join(p for p in (number, state, suffix) if p)


def read_rows(pdf_path: str):
    import pdfplumber
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for r in table:
                    rows.append([re.sub(r"\s+", " ", c or "").strip() for c in r])
    return rows


def build(pdf_path: str) -> dict:
    entries = {}
    skipped = []
    variants = set()
    last = None
    for r in read_rows(pdf_path):
        if len(r) < 3 or r[0] == "Form Name":
            continue
        name, edition, title = r[0], r[1], r[2]
        if not name and not edition and title and last is not None:
            last["title"] = f"{last['title']} {title}".strip()   # a title carried onto the next row
            continue
        m = _NAME_RE.match(name)
        if not m or not edition:
            if name:
                skipped.append(name)
            last = None
            continue
        number, state, suffix = m.group(1), m.group(2) or "", m.group(3) or ""
        if state and state not in _GEO_CODES:
            variants.add(name)
            last = None
            continue
        fid = form_id_for(number, state, suffix)
        key = edition_key(edition)
        e = entries.get(fid)
        if e is None:
            e = entries[fid] = {"form_id": fid, "number": number, "state": state, "suffix": suffix,
                                "title": title, "edition": edition, "_key": key, "editions": 0}
        e["editions"] += 1
        if key >= e["_key"]:
            e.update(title=title, edition=edition, _key=key)
        last = e if key >= e["_key"] else None
    forms = []
    for e in sorted(entries.values(), key=lambda x: (int(x["number"]), x["state"], x["suffix"])):
        e.pop("_key", None)
        forms.append(e)
    return {
        "source": os.path.basename(pdf_path),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "ASG's supported-forms list, text only. Editions are for search; generation asks ASG for the latest.",
        "count": len(forms),
        "skipped_names": sorted(set(skipped)),
        "skipped_variants": sorted(variants),
        "forms": forms,
    }


# Forms ASG served correctly on 4 Nov 2026 that its ACORD-source catalogue does not list (another publisher's form).
_PROVEN_EXTRA = [
    {"form_id": "ACORD_125_CIS", "number": "125", "state": "", "suffix": "CIS",
     "title": "Commercial Insurance Application - Contact Information Schedule", "edition": "2009/08", "editions": 1,
     # not in the catalogue, so there is no row to mirror: the request PROVEN on production (4 Nov 2026) - latest + CIS
     "request": {"latest": True, "geoCodeSuffix": "CIS"}},
]


# ASG's catalogue typos, and the characters it lost as "?" (live search, 4 Nov 2026): quotes, apostrophes, dashes.
# Order matters - a quoted phrase first, then possessives, then a dash. Plain ASCII out (no em-dashes in UI text).
_TITLE_FIXES = (
    (re.compile(r"\bnderlying\b"), "Underlying"),
    (re.compile(r"(?<=\s)\?(\w[^?]*\w)\?(?=\s|$)"), r'"\1"'),   # ?Workers Compensation Act? -> "..."
    (re.compile(r"(?<=\w)\?(?=s\b)"), "'"),                       # Operator?s -> Operator's
    (re.compile(r"(?<=s)\?(?=\s)"), "'"),                          # Workers? Compensation -> Workers' Compensation
    (re.compile(r"\s\?\s"), " - "),                                # Supplement ? Selection -> Supplement - Selection
    (re.compile(r"(?<=\s)\?(?=\w)"), "- "),                        # Inc. ?Instructions -> Inc. - Instructions
    # review C (4 Nov 2026): typos in ASG's own titles, and plain ASCII (no em / en dashes or curly quotes in UI text)
    (re.compile(r"\bFloirda\b", re.I), "Florida"),
    (re.compile(r"\bLiabiilty\b", re.I), "Liability"),
    (re.compile(r"\bAddenedum\b", re.I), "Addendum"),
    (re.compile(r"\bNew Yorker (?=Workers)", re.I), "New York "),
    (re.compile(r"\s*[\u2013\u2014]\s*"), " - "),
    (re.compile(r"[\u2018\u2019]"), "'"),
    (re.compile(r"[\u201c\u201d]"), '"'),
    (re.compile(r"\s{2,}"), " "),
)

# A file name says what the form IS: "PNC_FRM_UCA_BUSINESSOWNERS-(BOP)-APPLICATION-CHECKLIST_202406_856_ACRO.pdf".
_SLUG_RE = re.compile(r"(?:^|/)(?:PNC_)?FRM_U[A-Za-z]{2,4}_(?P<slug>.+?)_\d{6}_\d+[A-Za-z_]*_ACRO\.pdf$", re.I)
_DOC_WORDS = ("CHECKLIST", "INSTRUCTIONS", "WORKSHEET")
_SLUG_STOP = {"ACORD", "FORM", "AND", "OF", "THE", "FOR", "TO", "IN", "ON", "OR", "SECTION", "INSURANCE", "ACRO"}
_STATE_WORDS = {"ALABAMA", "ALASKA", "ARIZONA", "ARKANSAS", "CALIFORNIA", "COLORADO", "CONNECTICUT", "DELAWARE", "FLORIDA",
                "GEORGIA", "HAWAII", "IDAHO", "ILLINOIS", "INDIANA", "IOWA", "KANSAS", "KENTUCKY", "LOUISIANA", "MAINE",
                "MARYLAND", "MASSACHUSETTS", "MICHIGAN", "MINNESOTA", "MISSISSIPPI", "MISSOURI", "MONTANA", "NEBRASKA",
                "NEVADA", "OHIO", "OKLAHOMA", "OREGON", "PENNSYLVANIA", "TENNESSEE", "TEXAS", "UTAH", "VERMONT",
                "VIRGINIA", "WASHINGTON", "WISCONSIN", "WYOMING"}
_STATE_NAMES = {"AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS", "CA": "CALIFORNIA", "CO": "COLORADO",
                "CT": "CONNECTICUT", "DE": "DELAWARE", "FL": "FLORIDA", "GA": "GEORGIA", "HI": "HAWAII", "ID": "IDAHO",
                "IL": "ILLINOIS", "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS", "KY": "KENTUCKY", "LA": "LOUISIANA",
                "ME": "MAINE", "MD": "MARYLAND", "MA": "MASSACHUSETTS", "MI": "MICHIGAN", "MN": "MINNESOTA",
                "MS": "MISSISSIPPI", "MO": "MISSOURI", "MT": "MONTANA", "NE": "NEBRASKA", "NV": "NEVADA", "NH": "NEW HAMPSHIRE",
                "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "NY": "NEW YORK", "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA",
                "OH": "OHIO", "OK": "OKLAHOMA", "OR": "OREGON", "PA": "PENNSYLVANIA", "RI": "RHODE ISLAND",
                "SC": "SOUTH CAROLINA", "SD": "SOUTH DAKOTA", "TN": "TENNESSEE", "TX": "TEXAS", "UT": "UTAH", "VT": "VERMONT",
                "VA": "VIRGINIA", "WA": "WASHINGTON", "WV": "WEST VIRGINIA", "WI": "WISCONSIN", "WY": "WYOMING",
                "DC": "DISTRICT OF COLUMBIA"}


_CORE_NUMBERS = frozenset({"25", "28", "101", "125", "126", "127", "130", "131", "133", "137", "138", "140", "141",
                           "160", "186"})


def _slug_of(r: dict) -> str:
    m = _SLUG_RE.search(str(r.get("acroFileName") or ""))
    return re.sub(r"[-_]+", " ", m.group("slug")).strip() if m else ""


def _words(text: str) -> set:
    return {w for w in re.findall(r"[A-Z]+", str(text or "").upper()) if len(w) > 2 and w not in _SLUG_STOP}


def _norm_title(text: str) -> str:
    return " ".join(re.findall(r"[A-Z0-9]+", str(text or "").upper()))


def _title_names_other_state(title: str, state: str) -> bool:
    """A state form titled after ANOTHER state and not its own (ASG's 63 OK "Ohio Fraud Statement")."""
    if not state or state not in _STATE_NAMES:
        return False
    t = f" {_norm_title(title)} "
    own = _STATE_NAMES[state]
    if f" {own} " in t:
        return False
    for code, name in _STATE_NAMES.items():
        if code == state or f" {name} " not in t:
            continue
        if any(f" {other} " in t and name in other and other != name for other in _STATE_NAMES.values()):
            continue                                  # "Virginia" inside "West Virginia"
        return True
    return False


def _contradiction(r: dict, title: str, state: str, number: str, core_titles: dict) -> str:
    """Why this row's own data contradicts itself (review C, 4 Nov 2026) - "" when it does not:
    - its FILE is another form (137 WA 2024/02's file is Maryland's EUIM offer): title and file name share no words;
    - it is titled after another state (63 OK "Ohio Fraud Statement");
    - it presents itself as one of the core ACORD applications under another number (66 CO's rows are titled and
      filed as the Commercial Insurance Application)."""
    slug = _slug_of(r)
    tw, sw = _words(title) - _STATE_WORDS, _words(slug) - _STATE_WORDS
    if tw and sw and not (tw & sw) and len(tw & sw) / max(1, min(len(tw), len(sw))) < 0.5:
        return "file is another form"
    if _title_names_other_state(title, state):
        return "titled after another state"
    for core_number, core in core_titles.items():
        if core_number != number and core and (_norm_title(title) == core or _norm_title(slug) == core):
            return f"presents itself as ACORD {core_number}"
    return ""


def _row_identity(r: dict):
    """(number, state, variant, code_in_name_only) a catalogue row is OUR form for - or None when its name cannot be
    read. `code_in_name_only`: ASG keeps the row's state / variant ONLY in its name. Asked WITHOUT a geoCode such a row
    is refused ("no acroform PDF" - 61 VA, 137 LA 2026/02, proof calls 4 Nov 2026); asked WITH the state read from its
    name it is served (61 VA, 137 LA 2026/02 - second proof round, 4 Nov 2026). A VARIANT code kept only in the name
    (131 S, 140 S, 25 N) is unproven and never chosen.

    A US state geoCode is the state. ASG's other geo codes (FR, US, WM, N, S, BM, CLAP, LOB, e) and its geoCodeSuffix
    (INS, S) are the form's VARIANT - shown, searched and labelled like INS ("ACORD 829 LOB"). ASG sometimes files a
    form with its code only in the NAME ("61_VA", "137_LA" 2026/02, "25-S", "131_-S"): read from there. A name that is
    neither ("50_WM TR_NJ") is reported, never guessed."""
    number = str(r.get("number") or "").strip()
    if not number.isdigit():
        return None
    geo = str(r.get("geoCode") or "").strip().upper()
    sfx = str(r.get("geoCodeSuffix") or "").strip().upper()
    if (geo and geo not in _GEO_CODES and sfx) or sfx in _GEO_CODES:
        return None      # two variant codes at once, or a suffix that reads as a state: none today - not guessed
    state = geo if geo in _GEO_CODES else ""
    variant = sfx or ("" if state else geo)
    name = re.sub(r"[\s_\-]+", "_", str(r.get("name") or "").strip().upper()).strip("_")
    if name and name.replace("_", "") != "".join(p for p in (number, geo, sfx) if p):
        m = re.match(r"^(\d+)_([A-Z]{1,4})$", name)
        if not (m and m.group(1) == number and not geo and not sfx):
            return None
        code = m.group(2)
        state, variant = (code, "") if code in _GEO_CODES else ("", code)
        return number, state, variant, True
    return number, state, variant, False


def _request_key(r: dict) -> tuple:
    """What ASG's own portal sends for this row (owner's DevTools capture, 4 Nov 2026): formNumber, edition, geoCode
    only when the row has one, geoCodeSuffix only when it has one. A missing code is "none" - the portal's 84 INS
    request (edition 2013/09 + INS, no geoCode) got the INS row although a plain 84 also exists at 2013/09."""
    return (str(r.get("number") or "").strip(), str(r.get("geoCode") or "").strip().upper(),
            str(r.get("geoCodeSuffix") or "").strip().upper(), str(r.get("edition") or "").strip())


def build_from_catalogue(json_path: str) -> dict:
    """ASG's REAL download catalogue (4 Nov 2026): the production portal's Forms tab list, captured from the page's own
    request `search?pageSize=5000&pageNum=0&geoCode=All` (ASG_TRANSCRIBER.md).

    One entry per form + state + variant, at ASG's NEWEST edition that has a fillable file ("..._ACRO.pdf" - a flat
    PDF has no boxes to fill). A row with its state only in its NAME is asked with that state as the geoCode (proven 4
    Nov 2026: 61 VA, 137 LA 2026/02); one with a variant code only in its name is unproven and never chosen.
    Each entry records `request`: exactly the fields ASG's portal sends for that row, so the download asks for THAT
    row - never "latest" (the 4 Nov deep check: "latest" landed on a flat edition for 5 forms, and two state forms
    filed without a state code matched nothing). A row whose request fields are shared with another row is
    ambiguous - even the portal could not tell them apart - so it is never chosen. `downloadInd` is NOT used (ACORD
    50 NY is marked "0" and downloads)."""
    with open(json_path, encoding="utf-8") as f:
        rows = json.load(f)
    def request_of(r: dict) -> tuple:
        # what we SEND for a row: its own fields, except that a state kept only in the row name is sent as the
        # geoCode (proven 4 Nov 2026 - see `_row_identity`)
        number, geo, sfx, edition = _request_key(r)
        ident = _row_identity(r)
        if ident and ident[3] and ident[1] and not geo:
            geo = ident[1]
        return number, geo, sfx, edition

    keys: dict = {}
    for r in rows:
        k = request_of(r)
        keys.setdefault(k, []).append(r)

    def ambiguous_request(r: dict) -> bool:
        # Two rows sharing one request are ambiguous - unless every one of them is a FILLABLE row of the same form (62
        # AK 2022/12 is listed coded AND name-only: one request, one form, either file is right).
        group = keys[request_of(r)]
        if len(group) == 1:
            return False
        ids = {(_row_identity(x) or ("?",))[:3] for x in group}
        return len(ids) > 1 or not all(str(x.get("acroFileName") or "").endswith("_ACRO.pdf") for x in group)
    # How many FILLABLE rows share each number + edition (any code, name-only rows included): a form whose code the
    # footer does not print is proven by its edition only when no other fillable row has that edition (review A,
    # 4 Nov 2026: 49 state forms share their edition with the plain form).
    shared: dict = {}
    for r in rows:
        if str(r.get("acroFileName") or "").endswith("_ACRO.pdf"):
            k2 = (str(r.get("number") or "").strip(), edition_key(str(r.get("edition") or "")))
            shared[k2] = shared.get(k2, 0) + 1
    by_id: dict = {}
    titles: dict = {}
    skipped, no_fillable, ambiguous, name_only = set(), set(), set(), set()
    passed_over, contradictory = set(), set()
    # The core applications' own titles (the plain, newest fillable row of each of our 17 numbers) - a row of ANOTHER
    # number titled or filed as one of them contradicts itself (66 CO - review C, 4 Nov 2026).
    core_titles: dict = {}
    for r in rows:
        n = str(r.get("number") or "").strip()
        if (n in _CORE_NUMBERS and not str(r.get("geoCode") or "").strip() and not str(r.get("geoCodeSuffix") or "").strip()
                and str(r.get("acroFileName") or "").endswith("_ACRO.pdf") and r.get("title")):
            best = core_titles.get(n)
            if best is None or edition_key(str(r.get("edition") or "")) > best[0]:
                core_titles[n] = (edition_key(str(r.get("edition") or "")), _norm_title(r["title"]))
    core_titles = {n: t for n, (_k, t) in core_titles.items()}
    all_by_id: dict = {}
    for r in rows:
        ident = _row_identity(r)
        if ident is None:
            skipped.add(str(r.get("name") or r.get("number") or "?").strip())
            continue
        number, state, variant, code_in_name_only = ident
        fid = form_id_for(number, state, variant)
        title = str(r.get("title") or "").strip()
        if title:
            titles.setdefault(fid, title)
        all_by_id.setdefault(fid, []).append(r)
        if code_in_name_only and not state:
            name_only.add(fid)                        # a variant only in the name: unproven - never chosen
            continue
        if not str(r.get("acroFileName") or "").endswith("_ACRO.pdf"):
            no_fillable.add(fid)
            continue
        if ambiguous_request(r):
            ambiguous.add(fid)
            passed_over.add(f"{fid}@{str(r.get('edition') or '').strip()}")   # reported, never silent
            continue
        why = _contradiction(r, title, state, number, core_titles)
        if why:
            contradictory.add(f"{fid}@{str(r.get('edition') or '').strip()}: {why}")   # the next edition is used
            continue
        edition = str(r.get("edition") or "").strip()
        key = edition_key(edition)
        e = by_id.get(fid)
        if e is None:
            e = by_id[fid] = {"form_id": fid, "number": number, "state": state, "suffix": variant,
                              "title": title, "edition": edition, "_key": key, "editions": 0, "request": None}
        e["editions"] += 1
        coded = bool(str(r.get("geoCode") or "").strip()) or not code_in_name_only
        if e["request"] is None or key > e["_key"] or (key == e["_key"] and coded and e.get("_from_name")):
            # the newest requestable row; at the same edition the row ASG coded wins over the name-only one
            request = {"edition": edition,
                       "geoCode": str(r.get("geoCode") or "").strip() or (state if code_in_name_only else ""),
                       "geoCodeSuffix": str(r.get("geoCodeSuffix") or "").strip()}
            e["_from_name"] = not coded
            # The edition ASG's own FILE carries, when its catalogue says another (61 NY: row 2026/04, file
            # "..._202504_61_ACRO.pdf") - the footer of the right file prints that one (review A, 4 Nov 2026).
            fm = re.search(r"_(\d{4})(\d{2})_\d+[A-Z_]*_ACRO\.pdf$", str(r.get("acroFileName") or ""), re.I)
            if fm and f"{fm.group(1)}/{fm.group(2)}" != key and 1 <= int(fm.group(2)) <= 12:
                request["file_edition"] = f"{fm.group(1)}/{fm.group(2)}"
            e.update(edition=edition, _key=key, title=title or e["title"], request=request,
                     unique_edition=shared.get((number, key), 0) <= 1, _row=r)
    def fixed(text: str) -> str:
        for bad, good in _TITLE_FIXES:       # ASG's own catalogue typos (212: "Commercial Umbrella nderlying Schedule")
            text = bad.sub(good, text)
        return text.strip()

    for fid, e in by_id.items():
        row = e.pop("_row", None) or {}
        slug = _slug_of(row)
        # a blank title reads from the file name (3827: "Business Package Application for Insurance (Australia)")
        e["title"] = e["title"] or titles.get(fid, "") or titles.get(form_id_for(e["number"], "", ""), "") or slug
        # The file says it is a CHECKLIST / INSTRUCTIONS / WORKSHEET and the title does not (856 CA 2024/06 titled
        # "...Application for Businessowners" while its file is the BOP application checklist): an honest title.
        upper = e["title"].upper()
        for word in _DOC_WORDS:
            if word in slug.upper() and word not in upper:
                own = next((str(x.get("title") or "") for x in all_by_id.get(fid, []) if word in str(x.get("title") or "").upper()), "")
                e["title"] = own or f"{e['title']} - {word.title()}"
                break
        e["title"] = fixed(e["title"])
        # Older titles that START with the newest one keep their dropped subtitle for SEARCH ("Insurance Supplement" ->
        # "... Notice of Terrorism Insurance Coverage", 60 / 62 / 64 US) - shown title unchanged.
        newest = _norm_title(e["title"])
        aka = sorted({fixed(str(x.get("title") or "")) for x in all_by_id.get(fid, [])
                      if newest and _norm_title(x.get("title")).startswith(newest) and _norm_title(x.get("title")) != newest})
        if aka:
            e["aka"] = aka[:3]
        if "AUSTRALIA" in (upper + " " + slug.upper()):
            e["region"] = "AU"            # listed (owner, 4 Nov), ranked after the US forms
        # The editions of the OTHER form of this number whose footer prints no code either (a plain form and its INS
        # version): a differing printed edition is then that other form, never a mislabelled edition (review, 4 Nov).
        if not e["state"]:
            sfx_self = str((e.get("request") or {}).get("geoCodeSuffix") or "").upper()
            twins = set()
            for x in rows:
                if (str(x.get("number") or "").strip() != e["number"] or str(x.get("geoCode") or "").strip()
                        or not str(x.get("acroFileName") or "").endswith("_ACRO.pdf")):
                    continue
                sfx = str(x.get("geoCodeSuffix") or "").strip().upper()
                ident = _row_identity(x)
                if (sfx != sfx_self) and not (ident and ident[3]):
                    twins.add(edition_key(str(x.get("edition") or "")))
            twins.discard("0000/00")
            twins.discard(edition_key(str((e.get("request") or {}).get("edition") or "")))   # its own edition is not a twin's
            if twins:
                e["twin_editions"] = sorted(twins)
    for extra in _PROVEN_EXTRA:
        by_id.setdefault(extra["form_id"], dict(extra, _key=edition_key(extra["edition"])))
    forms = []
    for e in sorted(by_id.values(), key=lambda x: (int(x["number"]), x["state"], x["suffix"])):
        e.pop("_key", None)
        e.pop("_from_name", None)
        forms.append(e)
    return {
        "source": os.path.basename(json_path),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": ("ASG's production download catalogue (portal Forms tab, captured 4 Nov 2026): every form + state + "
                 "variant, its newest FILLABLE edition, and the exact request ASG's portal sends for it. Text only."),
        "count": len(forms),
        "skipped_names": sorted(skipped),
        "skipped_no_fillable": sorted(no_fillable - set(by_id)),
        "skipped_ambiguous": sorted(ambiguous - set(by_id)),
        # forms ASG lists only under rows whose VARIANT code is in the NAME alone - unproven, never chosen
        "skipped_code_in_name_only": sorted(name_only - set(by_id)),
        # rows whose own data contradicts itself (review C) - the form keeps its next consistent edition, or leaves
        "contradictory_rows_passed_over": sorted(contradictory),
        "skipped_contradictory": sorted({c.split("@")[0] for c in contradictory} - set(by_id)),
        # fillable rows passed over because another row shares their exact request (the form keeps an older row)
        "ambiguous_rows_passed_over": sorted(passed_over),
        "forms": forms,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    idx = build_from_catalogue(argv[1]) if argv[1].lower().endswith(".json") else build(argv[1])
    if len(argv) > 2:
        global OUT
        OUT = argv[2]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(idx, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"{idx['count']} forms written to {os.path.normpath(OUT)}; skipped names: {idx['skipped_names']}; "
          f"no fillable file: {len(idx.get('skipped_no_fillable') or [])}; "
          f"ambiguous: {idx.get('skipped_ambiguous') or idx.get('skipped_variants') or []}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
