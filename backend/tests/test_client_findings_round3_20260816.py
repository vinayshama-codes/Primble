# Round 3 (run 7e95e3ae), pinned with the run's LITERAL values. The client's
# six items and every round-1/2 fix HELD on this run; these close what it
# surfaced, each fixed at the CLASS after round 2 proved instance-narrow
# guards get outflanked:
#
#   K1  "0482854" returned as a policy key with FOUR coverage lines - the
#       single-entry guard was outflanked by multi-entry attribution. THE
#       INVARIANT: a contract key must be printed under a policy-labelled
#       entry somewhere; an unwitnessed key is cleared everywhere.
#   K2  127 RADIUS = 104 - the Drive-Other-Car TERRITORY, misfiled by call-1
#       into the vehicle schedule's radius column, stamped because the
#       resolver trusted the schedule fact over the dec's printed "RADIUS: NA".
#       The dec cell now runs FIRST and its NA vetoes.
#   K3  Fabricated small counts/percents: "1 story / 1 unit" (131 row #28),
#       "# EMPL 1", "30%" twice (125). Fact-or-blank families.
#   K4  Q4 printed the OCR letter-spaced "6 C 7 - 4 0 - 0 2---26" - the only
#       printing that survived verification this run. Elected keys now repair
#       the letter-spacing fingerprint; values keep the verbatim printing.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402
from services.extraction_service import _canonicalise_dec_entry_keys  # noqa: E402


def _e(label, value, pol=None, lob=None, owner="policy"):
    return {"label": label, "value": value, "section": None,
            "owner": owner, "policy_number": pol, "line_of_business": lob}


# ── K1: the contract-key invariant ───────────────────────────────────────────

def _run_7e95e3ae_keys():
    """The literal shape: the account number keyed to FOUR common-dec entries,
    beside real contracts each witnessed under a policy label."""
    return [
        _e("Account Number", "0482854", pol="0482854"),
        _e("Section 1 Coverage", "Property", pol="0482854", lob="Property"),
        _e("Section 2 Coverage", "Liability", pol="0482854",
           lob="General Liability"),
        _e("Section 3 Coverage", "Crime and Fidelity", pol="0482854", lob="Crime"),
        _e("Policy", "BBC7263 - 26", pol="BBC7263 - 26", lob="General Liability"),
        _e("POLICY NUMBER", "6E7-40-02---26", pol="6E7-40-02---26",
           lob="Commercial Auto"),
        _e("COVERED AUTOS LIABILITY - PREMIUM", "$ 1,496.00",
           pol="6E7-40-02---26", lob="Commercial Auto"),
    ]


def test_the_multi_entry_account_number_key_is_cleared_everywhere():
    entries = _run_7e95e3ae_keys()
    _canonicalise_dec_entry_keys(entries)
    keys = {e["policy_number"] for e in entries}
    assert "0482854" not in keys
    assert {"BBC7263 - 26", "6E7-40-02---26"} <= keys
    # entries and values survive; only the phantom KEY is gone
    assert entries[0]["value"] == "0482854"


def test_a_key_witnessed_under_any_printing_survives():
    """The witness match is canonical: 'BBC7263' under a policy label
    witnesses the 'BBC7263 - 26' key."""
    entries = [
        _e("Commercial General Liability - Policy Number", "BBC7263",
           pol="BBC7263 - 26", lob="General Liability"),
        _e("General Aggregate Limit", "$2,000,000", pol="BBC7263 - 26",
           lob="General Liability"),
        _e("POLICY NO", "6E7-40-02---26", pol="6E7-40-02---26",
           lob="Commercial Auto"),
    ]
    _canonicalise_dec_entry_keys(entries)
    assert {e["policy_number"] for e in entries} == {"BBC7263 - 26",
                                                     "6E7-40-02---26"}


def test_the_invariant_stands_aside_when_no_policy_labels_exist():
    """CONDITIONAL by design: a recording with no policy labels anywhere gives
    the invariant no basis, and every synthetic fixture in the older tests
    keeps its keys - nothing previously green may go red."""
    entries = [_e("L", "V", pol="SOME-KEY-1"), _e("L", "V2", pol="SOME-KEY-2")]
    _canonicalise_dec_entry_keys(entries)
    assert {e["policy_number"] for e in entries} == {"SOME-KEY-1", "SOME-KEY-2"}


# ── K2: the dec's printed cell vetoes the polluted schedule fact ─────────────

_AUTO_DEC = [
    _e("RADIUS", "NA", pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("POLICY NUMBER", "6E7-40-02---26", pol="6E7-40-02---26",
       lob="Commercial Auto"),
]


def test_the_doc_territory_in_the_schedule_fact_cannot_beat_the_decs_na():
    """THE LITERAL RUN: schedule radius column carries 104 (the DOC territory);
    the dec prints RADIUS: NA. Blank wins."""
    facts = {"dec_page_entries": _AUTO_DEC,
             "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772",
                                    "radius": "104"}]}
    assert ps._resolve_vehicle_rating_cell("Vehicle_RadiusOfUse_A", facts) is None


def test_a_dec_stated_radius_beats_the_schedule_column():
    facts = {"dec_page_entries": [
        _e("RADIUS", "150", pol="6E7-40-02---26", lob="Commercial Auto")],
        "auto_vin_schedule": [{"radius": "104"}]}
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_RadiusOfUse_A", facts) == "150"


def test_the_schedule_still_fills_where_the_dec_is_silent():
    """No SEAT entry on the dec -> the schedule's seats column still stamps."""
    facts = {"dec_page_entries": _AUTO_DEC,
             "auto_vin_schedule": [{"seats": "5"}]}
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_SeatingCapacityCount_A", facts) == "5"


# ── K3: count / percent boxes - a fact or an owned blank ─────────────────────

def test_the_131_employee_count_stamps_the_documents_own_statement():
    facts = {"num_employees": "0 - 25"}
    assert ps._resolve_exposure_count(
        "BusinessInformation_EmployeeCount_A", facts) == "0 - 25"


def test_the_131_employee_count_is_an_owned_blank_without_a_fact():
    assert ps._resolve_exposure_count(
        "BusinessInformation_EmployeeCount_A", {}) is None
    assert ps._is_authoritative_blank_field(
        "BusinessInformation_EmployeeCount_A", {})


def test_row_28_is_an_owned_blank_family():
    """The literal fabrications: 1 story, 1 unit (and the earlier 0 pools /
    0 diving boards, closing that row for good)."""
    for f in ("ExcessUmbrella_PropertyRating_StructureStoreyCount_A",
              "ExcessUmbrella_PropertyRating_ApartmentCount_A",
              "ExcessUmbrella_PropertyRating_SwimmingPoolCount_A",
              "ExcessUmbrella_PropertyRating_DivingBoardCount_A"):
        assert ps._is_authoritative_blank_field(f, {}), f


def test_the_percent_boxes_are_deliberately_not_owned():
    """WITHDRAWN by the regression wall, on purpose: the percent boxes carry a
    test-pinned 2026-08-14 contract - a documented percentage survives with
    its citation. A blanket blank here would delete legitimate answers; the
    fabricated 30% is a quote-gate defeat to fix from the run log instead."""
    assert not ps._is_authoritative_blank_field(
        "CommercialStructure_InstallationRepairWorkPercent_A", {})


# ── K4: OCR letter-spacing repair on elected keys ────────────────────────────

def test_the_only_surviving_spaced_printing_elects_despaced():
    entries = [
        _e("POLICY NUMBER", "6 C 7 - 4 0 - 0 2---26",
           pol="6 C 7 - 4 0 - 0 2---26", lob="Inland Marine"),
    ]
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["policy_number"] == "6C7-40-02---26"
    assert entries[0]["value"] == "6 C 7 - 4 0 - 0 2---26"   # evidence intact


def test_an_ordinarily_spaced_printing_is_never_despaced():
    """'BBC7263 - 26' has ONE-character tokens only around '-', which is not
    alphanumeric - the fingerprint cannot match. Pinned so the repair can
    never touch the canonical GL key that every other test expects."""
    entries = [_e("Policy", "BBC7263 - 26", pol="BBC7263 - 26",
                  lob="General Liability")]
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["policy_number"] == "BBC7263 - 26"
