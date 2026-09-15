"""Orbin round 3 - every value that belongs to ONE coverage line stays with it.

Client review of the Orbin package (diagnosed 14 Sep 2026): the right data was
found and attached to the wrong policy, line or box. Five reported defects, all
reproduced offline on the live session's own per-document facts:

  1. carrier / NAIC / policy number / dates drifting between lines
  2. "IM 7100 06 04" (an AAIS form number) in ACORD 125's policy-number box
  3. ACORD 126 pairing Employers Mutual Casualty with EMC P&C's NAIC 25186
  4. territory 6679 (Auto Drive Other Car) on the ACORD 126 hazard grid
  5. GL class 91580 on the ACORD 127 vehicle row

Every fixture below uses the client's literal values and the SHAPES the live
session actually carries (a page-1 premium summary that prints no carrier, the
AAIS page footer read as a coverage line, the certificate's INSURER roster).
"""
import copy

import pytest

import services.arq_service as arq
import services.extraction_service as es
import services.pdf_service as ps
import services.underwriting_consistency as uc

VIN = "4S4BRCGC9C3217772"

POLICY_TEXT = """[Document page 1]
Account Number: 0482854
Common Declarations
Named Insured
, ORBIN CONTRACTING LLC
Coverages and Premium
Section Coverage Premium
1 Property No Coverage
2 Liability $3,954.00
4 Inland Marine $300.00
5 Automobile $2,991.00
7 Umbrella $3,418.00
Estimated Total Policy Premium $10,663.00
[Document page 3]
EMPLOYERS MUTUAL CASUALTY COMPANY
COMMERCIAL INLAND MARINE DECLARATIONS
*------------------------*
POLICY PERIOD: FROM 07/15/25 TO 07/15/26 * POLICY NUMBER *
*6C7-40-02---26*
*------------------------*
TOTAL INLAND MARINE PREMIUM $ 300.00
FORM: CM7000A ED. 3-20 BPP 07/15/25 027 SB 6C74002 2601
[Document page 44]
AAIS
IM 7100 06 04
INSTALLATION FLOATER COVERAGE
After this policy has been in effect 60 days or
more, or if it is a renewal of a policy issued by
"us" effective immediately, "we" may cancel
IM 7100 06 04
[Document page 89]
EMPLOYERS MUTUAL CASUALTY COMPANY POLICY NO: 6E7-40-02---26
ORBIN CONTRACTING LLC EFF DATE: 07/15/25 EXP DATE: 07/15/26
COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO
ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN
LOC: 001 4800 DAHLIA STREET D13
VEH NO 1 TERR: 111 .
2012 SUBARU OUTBACK SEDAN ID NO 4S4BRCGC9C3217772.
ADDITIONAL INFORMATION:
COST NEW: 26680 RADIUS: NA USE: NA .
AGE: LIAB-I PHYS-I .
PRIV PASSENGER - COMM CLASS: 7383 .
COVERED AUTOS LIABILITY .$ 1,496.00
CA7001A 02-22 BPP 07/15/25 027 SB 6E74002 2601
[Document page 91]
EMPLOYERS MUTUAL CASUALTY COMPANY POLICY NO: 6E7-40-02---26
ORBIN CONTRACTING LLC EFF DATE: 07/15/25 EXP DATE: 07/15/26
ENDORSEMENT PREMIUM DETAIL
ENDORSEMENTS CLASS PREMIUM
DRIVE OTHER CAR - TERRITORY: 104 6679 $ 204.00
Auto Elite Extension 8556 $ 250.00
ENDST-A BPP 07/15/25 027 SB 6E74002 2601
[Document page 144]
EMPLOYERS MUTUAL CASUALTY COMPANY POLICY NO: 6J7-40-02---26
ORBIN CONTRACTING LLC EFF DATE: 07/15/25 EXP DATE: 07/15/26
COMMERCIAL UMBRELLA DECLARATIONS
Each Occurrence Limit (Liability Coverage) $ 3,000,000
CU7000 BPP 07/15/25 027 SB 6J74002 2601
[Document page 148]
EMPLOYERS MUTUAL CASUALTY COMPANY POLICY NO: 6J7-40-02---26
ORBIN CONTRACTING LLC EFF DATE: 07/15/25 EXP DATE: 07/15/26
COMMERCIAL UMBRELLA SCHEDULE
SCHEDULE OF UNDERLYING INSURANCE
Commercial General Liability
Company: EMC Property & Casualty Company
Policy Number: BBC7263
Commercial Auto Liability
Company: Employers Mutual Casualty Company
Policy Number: 6E74002
CU7001A 11-15 027 SB 6J74002 2601
[Document page 211]
EMC Property & Casualty Company
Policy: BBC7263 - 26
Policy Term: 07/15/2025-07/15/2026
General Liability Schedule
Location 001
91580 Contractors - Executive Supervisors 33.211 $1,305
Prem Basis: Payroll
Exposure: $39,300
91585 Contrctrs-sub work-in connection 3.4240 $1,198 2.293 $803
Prem Basis: Total Cost
Exposure: $350,000
Form CG7001A Ed. 10-12 07/15/2025 BBC7263 2601
"""

COI_TEXT = """CERTIFICATE OF LIABILITY INSURANCE DATE (MM/DD/YYYY)
INSURER A :EMCProperty&CasualtyCompany 25186
INSURER B :EmployersMutualCasualtyCo. 21415
A X COMMERCIAL GENERAL LIABILITY BBC7263 7/15/2025 7/15/2026 EACH OCCURRENCE $1,000,000
B AUTOMOBILE LIABILITY 6E74002 7/15/2025 7/15/2026 SINGLE LIMIT $1,000,000
B X UMBRELLA LIAB X OCCUR 6J74002 7/15/2025 7/15/2026 EACH OCCURRENCE $1,000,000
"""


def _entry(label, value, section, policy, line, owner="policy"):
    return {"label": label, "value": value, "section": section, "owner": owner,
            "policy_number": policy, "line_of_business": line}


def _policy_facts():
    return {
        "applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai",
                           "confidence": "ai_high"},
        "carrier_name": {"value": "EMPLOYERS MUTUAL CASUALTY COMPANY", "source": "ai",
                         "confidence": "ai_high"},
        "policy_number": {"value": "6E7-40-02---26", "source": "ai", "confidence": "ai_high"},
        "effective_date": {"value": "07/15/25", "source": "ai", "confidence": "ai_high"},
        "expiration_date": {"value": "07/15/26", "source": "ai", "confidence": "ai_high"},
        # The live shape: page-1 summary rows carrying a number and carrier the
        # page never prints, forms-list rows, and the AAIS footer as a "line".
        "coverage_lines": [
            {"line": "Liability", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
             "premium": "$3,954.00", "policy_number": "6C7-40-02---26",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
            {"line": "Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
             "premium": "$300.00", "policy_number": "6C7-40-02---26",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
            {"line": "Automobile", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
             "premium": "$2,991.00", "policy_number": "6C7-40-02---26",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
            {"line": "Umbrella", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
             "premium": "$3,418.00", "policy_number": "6C7-40-02---26",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
            {"line": "Installation Floater Coverage", "carrier": "AAIS", "naic": None,
             "premium": None, "policy_number": "IM 7100 06 04",
             "effective_date": None, "expiration_date": None},
            {"line": "Covered Autos Liability", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
             "naic": None, "premium": "$ 1,496.00", "policy_number": "6E7-40-02---26",
             "effective_date": "07/15/25", "expiration_date": "07/15/26"},
            {"line": "Commercial Umbrella", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
             "naic": None, "premium": "$ 3,418.00", "policy_number": "6J7-40-02---26",
             "effective_date": "07/15/25", "expiration_date": "07/15/26"},
            {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
             "naic": None, "premium": "$3,954.00", "policy_number": "BBC7263 - 26",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
            {"line": "Commercial General Liability", "carrier": "EMC Insurance", "naic": None,
             "premium": None, "policy_number": None, "effective_date": None,
             "expiration_date": None},
            {"line": "Commercial General Liability Coverage Part",
             "carrier": "Employers Mutual Casualty Company", "naic": None, "premium": None,
             "policy_number": None, "effective_date": None, "expiration_date": None},
        ],
        "underlying_policies": [
            {"line": "Commercial General Liability", "limit": "$ 1,000,000 Each Occurrence",
             "carrier": "EMC Property & Casualty Company", "policy_no": "BBC7263"},
            {"line": "Commercial Auto Liability", "limit": "$ 1,000,000 Each Accident",
             "carrier": "Employers Mutual Casualty Company", "policy_no": "6E74002"},
        ],
        "auto_vin_schedule": [{"vin": VIN, "year": "2012", "make": "SUBARU",
                               "model": "OUTBACK SEDAN", "body_type": "PRIV PASSENGER",
                               "comp_symbol": "07", "coll_symbol": "07", "gvw": None}],
        "gl_class_code_schedule": [
            {"location": "Location 001", "class_code": "91580", "territory": None,
             "classification": "Contractors - Executive Supervisors",
             "premium_basis": "Payroll", "exposure_amount": "$39,300"},
            {"location": "Location 001", "class_code": "91585", "territory": None,
             "classification": "Contrctrs-sub work-in connection",
             "premium_basis": "Total Cost", "exposure_amount": "$350,000"},
        ],
        "num_employees": {"value": "0 - 25", "source": "ai", "confidence": "ai_high"},
        "dec_page_entries": [
            _entry("Policy Number", "6C7-40-02---26", "COMMERCIAL INLAND MARINE DECLARATIONS",
                   "6C7-40-02---26", "Inland Marine"),
            _entry("POLICY NO", "6E7-40-02---26", "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO",
                   "6E7-40-02---26", "Commercial Auto"),
            _entry("PRIV PASSENGER - COMM CLASS", "7383",
                   "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO", "6E7-40-02---26",
                   "Commercial Auto"),
            _entry("DRIVE OTHER CAR - TERRITORY", "104 6679 $ 204.00",
                   "ENDORSEMENT PREMIUM DETAIL", "6E7-40-02---26", "Commercial Auto"),
            _entry("POLICY NO", "6J7-40-02---26", "COMMERCIAL UMBRELLA DECLARATIONS",
                   "6J7-40-02---26", "Commercial Umbrella"),
            _entry("Policy", "BBC7263 - 26", "General Liability Schedule",
                   "BBC7263 - 26", "General Liability"),
            _entry("Location 001", "91580 Contractors - Executive Supervisors",
                   "General Liability Schedule", "BBC7263 - 26", "General Liability"),
        ],
    }


def _coi_facts():
    return {
        "carrier_name": {"value": "EMC Property & Casualty Company", "source": "ai",
                         "confidence": "ai_high"},
        "carrier_naic": {"value": "25186", "source": "ai", "confidence": "ai_high"},
        "policy_number": {"value": "BBC7263", "source": "ai", "confidence": "ai_high"},
        "coverage_lines": [
            {"line": "Commercial General Liability", "naic": "25186",
             "carrier": "EMC Property & Casualty Company", "premium": None,
             "policy_number": "BBC7263", "effective_date": "7/15/2025",
             "expiration_date": "7/15/2026"},
            {"line": "Automobile Liability", "naic": "21415",
             "carrier": "Employers Mutual Casualty Co.", "premium": None,
             "policy_number": "6E74002", "effective_date": "7/15/2025",
             "expiration_date": "7/15/2026"},
            {"line": "Umbrella Liability", "naic": "21415",
             "carrier": "Employers Mutual Casualty Co.", "premium": None,
             "policy_number": "6J74002", "effective_date": "7/15/2025",
             "expiration_date": "7/15/2026"},
        ],
        "underlying_policies": [
            {"line": "Automobile Liability", "limit": "$1,000,000 combined single limit",
             "carrier": "Employers Mutual Casualty Co.", "policy_no": "6E74002"},
        ],
    }


def _docs():
    return [
        {"doc_id": "pol", "filename": "2526 Package Policy (Complete Copy).pdf",
         "doc_type": "dec_page", "text": POLICY_TEXT, "facts": _policy_facts(), "flags": {}},
        {"doc_id": "coi", "filename": "CRS COI FIO - Orbin CERT ONLY.pdf",
         "doc_type": "certificate", "text": COI_TEXT, "facts": _coi_facts(),
         "flags": {"is_certificate_doc": True}},
    ]


@pytest.fixture(scope="module")
def merged():
    docs = _docs()
    mf, mg = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, docs


def _ctx(mf, form_id):
    return {**mf, "_form_id": form_id}


def _schema(fid):
    return ps._all_form_schemas()[fid]


# ── 2. FORM NUMBERS: never a policy number, anywhere ─────────────────────────

def test_the_aais_footer_leaves_every_row(merged):
    mf, docs = merged
    for d in docs:
        for row in d["facts"].get("coverage_lines") or []:
            assert row.get("policy_number") != "IM 7100 06 04"
            assert row.get("carrier") != "AAIS"


def test_the_card_never_offers_a_form_number(merged):
    mf, docs = merged
    res = uc.assess_underwriting_consistency(docs, mf, {})
    for f in res.get("fields") or []:
        if f.get("fact_key") == "policy_number":
            shown = [v.get("display") for v in f.get("values") or []]
            assert not any("IM 7100" in str(s) or "IM 7201" in str(s) for s in shown), shown


def test_a_form_number_cannot_be_confirmed_or_applied(merged):
    mf, docs = merged
    with pytest.raises(ValueError):
        uc.validate_confirmation("policy_number", "IM 7100 06 04", docs=docs)
    # A session confirmed before the fix still holds one - it must not apply.
    out = uc.apply_confirmations(mf, {"policy_number": "IM 7100 06 04"}, docs=docs)
    assert es._fv(out, "policy_number") != "IM 7100 06 04"
    assert uc.validate_confirmation("policy_number", "6E7-40-02---26", docs=docs)


# ── 1/3. CARRIER + NAIC STAY WITH THEIR CONTRACT ─────────────────────────────

def test_each_contract_is_bound_to_the_carrier_in_its_own_page_header(merged):
    mf, docs = merged
    binding = es._contract_carriers_from_page_headers(docs, mf)
    assert binding[es._norm_policy_number("BBC7263 - 26")] == "EMC Property & Casualty Company"
    for pol in ("6E7-40-02---26", "6J7-40-02---26", "6C7-40-02---26"):
        assert binding[es._norm_policy_number(pol)] == "EMPLOYERS MUTUAL CASUALTY COMPANY"
    # The umbrella schedule prints the GL carrier in its BODY; only the header binds.
    assert binding[es._norm_policy_number("BBC7263")] == "EMC Property & Casualty Company"


def test_a_page_naming_two_contracts_binds_nothing():
    text = ("[Document page 1]\nACME INSURANCE COMPANY POLICY NO: AB12345 AND CD67890\n"
            "body\n")
    mf = {"coverage_lines": [{"line": "General Liability", "policy_number": "AB12345"},
                             {"line": "Business Auto", "policy_number": "CD67890"}]}
    assert es._contract_carriers_from_page_headers([{"text": text}], mf) == {}


def test_acord_126_prints_emc_pc_with_25186(merged):
    mf, _docs = merged
    ctx = _ctx(mf, "ACORD_126")
    assert ps._resolve_section_policy_identity("Insurer_FullName_A", ctx) == \
        "EMC Property & Casualty Company"
    assert ps._resolve_section_policy_identity("Insurer_NAICCode_A", ctx) == "25186"
    assert ps._resolve_section_policy_identity("Policy_PolicyNumberIdentifier_A", ctx) == \
        "BBC7263 - 26"


@pytest.mark.parametrize("fid,number", [("ACORD_127", "6E7-40-02---26"),
                                        ("ACORD_131", "6J7-40-02---26")])
def test_auto_and_umbrella_keep_employers_mutual_with_21415(merged, fid, number):
    mf, _docs = merged
    ctx = _ctx(mf, fid)
    name = ps._resolve_section_policy_identity("Insurer_FullName_A", ctx)
    assert ps._carrier_entity_key(name) == ps._carrier_entity_key("Employers Mutual Casualty Company")
    assert ps._resolve_section_policy_identity("Insurer_NAICCode_A", ctx) == "21415"
    assert ps._resolve_section_policy_identity("Policy_PolicyNumberIdentifier_A", ctx) == number


def test_inland_marine_gets_the_naic_its_company_is_printed_with(merged):
    """No certificate row names Inland Marine; the NAIC belongs to the ENTITY."""
    mf, _docs = merged
    ctx = _ctx(mf, "ACORD_138_CA")
    assert ps._resolve_section_policy_identity("Insurer_NAICCode_A", ctx) == "21415"


def test_two_naics_for_one_entity_is_no_naic():
    rows = [{"carrier": "Acme Mutual Company", "naic": "11111"},
            {"carrier": "ACME MUTUAL CO.", "naic": "22222"}]
    assert ps._naic_printed_with("Acme Mutual Company", rows) is None
    # ...and a DIFFERENT company's NAIC is never borrowed.
    assert ps._naic_printed_with("Acme Property Company", rows) is None


def test_the_package_scalars_are_a_printed_pair(merged):
    mf, _docs = merged
    assert es._fv(mf, "carrier_naic") == "21415"   # Employers Mutual's, not EMC P&C's


# ── 1. THE UNDERLYING GRID: one contract printed two ways is ONE contract ────

def test_acord_131_underlying_rows_fill_from_their_own_line(merged):
    mf, _docs = merged
    ctx = _ctx(mf, "ACORD_131")
    auto_no = ps._resolve_underlying_policy_row(
        "UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A", ctx)
    assert ps._same_policy_contract(auto_no, "6E74002")
    assert ps._carrier_entity_key(ps._resolve_underlying_policy_row(
        "UnderlyingPolicy_Automobile_InsurerFullName_A", ctx)) == \
        ps._carrier_entity_key("Employers Mutual Casualty Company")
    gl_no = ps._resolve_underlying_policy_row(
        "UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A", ctx)
    assert ps._same_policy_contract(gl_no, "BBC7263")


def test_two_different_contracts_still_conflict():
    assert ps._fold_contracts(["6E74002", "6E7-40-02---26", "BBC7263"]) == \
        ["6E7-40-02---26", "BBC7263"]


# ── 1. DATES: a cancellation clause does not make a renewal ──────────────────

def test_the_iso_cancellation_clause_is_not_a_renewal():
    for clause in ("After this policy has been in effect 60 days or\nmore, or if it is a "
                   "renewal of a policy issued by\n\"us\" effective immediately",
                   "a. If this policy has been in effect for 60 days\nor more, or is a "
                   "renewal of a policy we is-\nsued, we may cancel",
                   "fail to pay any premium deposit required for\nrenewal or to any policy "
                   "or coverage which\nhas been in effect less than 60 days, unless it\n"
                   "is a renewal policy.",
                   "we may decrease the coverage benefits on renewal of this policy"):
        mf = {}
        es._backfill_is_renewal(mf, clause)
        assert "is_renewal" not in mf, clause


@pytest.mark.parametrize("text", ["RENEWAL OF: 6E7-40-02---25\nSOME OTHER TEXT",
                                  "COMMERCIAL AUTO RENEWAL DECLARATIONS",
                                  "This policy is a renewal of BBC7263-25."])
def test_a_stated_renewal_still_counts(text):
    mf = {}
    es._backfill_is_renewal(mf, text)
    assert es._fv(mf, "is_renewal") == "yes"


def test_orbin_keeps_the_term_its_policies_print(merged):
    # The printed term is KEPT - as the current policy's term, in prior_*, no
    # longer as the proposed one (owner, 15 Sep 2026, following Brent's ACORD
    # 125 answer key: it ended 07/15/26, so the proposal is asked, never a
    # renewal-shifted date). The cancellation clause still makes no renewal.
    mf, _docs = merged
    assert not es._fv(mf, "is_renewal")
    assert es._fv(mf, "prior_effective_date") == "07/15/25"
    assert es._fv(mf, "prior_expiration_date") == "07/15/26"
    assert not es._fv(mf, "effective_date") and not es._fv(mf, "expiration_date")


# ── 5. THE VEHICLE'S OWN CLASS AND TERRITORY, READ BESIDE ITS OWN VIN ────────

def test_vehicle_codes_come_from_the_vin_block_not_the_doc_line(merged):
    mf, _docs = merged
    row = es._fv(mf, "auto_vin_schedule")[0]
    assert row["class_code"] == "7383"
    assert row["territory"] == "111"


def test_two_vehicles_never_share_a_block():
    vin2 = "1FTBF2B61KEC00001"
    text = (f"VEH NO 1 TERR: 111 .\n2012 SUBARU ID NO {VIN}.\nCOMM CLASS: 7383 .\n"
            f"VEH NO 2 TERR: 222 .\n2019 FORD ID NO {vin2}.\nCOMM CLASS: 01499 .\n")
    mf = {"auto_vin_schedule": [{"vin": VIN}, {"vin": vin2}]}
    es._backfill_vehicle_codes_from_text(mf, [{"text": text}])
    assert mf["auto_vin_schedule"][0] == {"vin": VIN, "class_code": "7383", "territory": "111"}
    assert mf["auto_vin_schedule"][1]["class_code"] == "01499"
    assert mf["auto_vin_schedule"][1]["territory"] == "222"


def test_a_stated_vehicle_code_is_never_overwritten():
    mf = {"auto_vin_schedule": [{"vin": VIN, "class_code": "7398"}]}
    es._backfill_vehicle_codes_from_text(mf, [{"text": f"ID NO {VIN}. CLASS: 7383"}])
    assert mf["auto_vin_schedule"][0]["class_code"] == "7398"


def test_127_stamps_7383_and_111(merged):
    mf, _docs = merged
    ctx = _ctx(mf, "ACORD_127")
    assert ps._resolve_schedule_row("Vehicle_RateClassCode_A", ctx) == "7383"
    assert ps._resolve_schedule_row("Vehicle_RatingTerritoryCode_A", ctx) == "111"


# ── 4/5. CODES STAY ON THEIR OWN LINE ────────────────────────────────────────

def test_a_gl_row_that_prints_no_territory_is_an_owned_blank(merged):
    mf, _docs = merged
    ctx = _ctx(mf, "ACORD_126")
    for row in ("A", "B"):
        f = f"GeneralLiability_Hazard_TerritoryCode_{row}"
        assert ps._resolve_gl_hazard_row(f, ctx) is None
        assert ps._is_authoritative_blank_field(f, ctx) is True
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_A", ctx) == "91580"


def test_a_gl_row_that_prints_a_territory_still_fills():
    facts = {"gl_class_code_schedule": [{"class_code": "91580", "territory": "003"}]}
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_TerritoryCode_A", facts) == "003"
    assert ps._is_authoritative_blank_field("GeneralLiability_Hazard_TerritoryCode_A", facts) is False


def test_the_fence_reads_the_verified_entries(merged):
    mf, _docs = merged
    gl = {"GeneralLiability_Hazard_TerritoryCode_A": "104",
          "GeneralLiability_Hazard_TerritoryCode_B": "6679",
          "GeneralLiability_Hazard_ClassCode_A": "91580"}
    out = ps._cross_line_code_borrows(gl, _schema("ACORD_126"), _ctx(mf, "ACORD_126"))
    assert set(out) == {"GeneralLiability_Hazard_TerritoryCode_A",
                        "GeneralLiability_Hazard_TerritoryCode_B"}
    auto = {"Vehicle_RateClassCode_A": "91580", "Vehicle_RatingTerritoryCode_A": "111"}
    out = ps._cross_line_code_borrows(auto, _schema("ACORD_127"), _ctx(mf, "ACORD_127"))
    assert set(out) == {"Vehicle_RateClassCode_A"}


def test_the_ebl_block_is_blank_on_a_package_without_ebl(merged):
    mf, _docs = merged
    ctx = _ctx(mf, "ACORD_126")
    for f in ("GeneralLiability_EmployeeBenefits_EmployeeCount_A",
              "GeneralLiability_EmployeeBenefits_LimitAmount_A"):
        assert ps._resolve_uncarried_coverage_part(f, ctx) is None
        assert ps._deterministic_map(f, ctx) is None
    with_ebl = {**ctx, "coverage_lines": list(es._fv(mf, "coverage_lines")) + [
        {"line": "Employee Benefits Liability", "premium": "$150"}]}
    assert ps._resolve_uncarried_coverage_part(
        "GeneralLiability_EmployeeBenefits_LimitAmount_A", with_ebl) is ps._SCHED_SKIP


# ── 2/3. NO POST-GENERATION DOOR MAY UNDO A RESOLVER'S BLANK ────────────────

def _generated():
    def form(fid, state):
        sch = _schema(fid)
        return {"schema": {k: sch[k] for k in state}, "mapped": dict(state),
                "confidence": {}, "guard_blanks": []}
    return {
        "ACORD_125": form("ACORD_125", {"Policy_PolicyNumberIdentifier_A": None}),
        "ACORD_126": form("ACORD_126", {"Insurer_FullName_A": None, "Insurer_NAICCode_A": None,
                                        "Policy_PolicyNumberIdentifier_A": "BBC7263 - 26"}),
        "ACORD_127": form("ACORD_127", {"Policy_PolicyNumberIdentifier_A": "6E7-40-02---26"}),
    }


def _legacy_facts(mf):
    """What a session confirmed before the fix holds: the form number as the
    package policy number and the recombined scalar pair."""
    return {**mf, "policy_number": {"value": "IM 7100 06 04", "source": "user_confirmed"},
            "carrier_naic": {"value": "25186", "source": "ai"}}


def test_the_late_stamp_cannot_print_the_form_number_or_the_wrong_pair(merged):
    mf, _docs = merged
    gen = _generated()
    arq._backfill_and_resolve_present(gen, _legacy_facts(mf))
    s125 = gen["ACORD_125"].get("field_state") or gen["ACORD_125"]["mapped"]
    s126 = gen["ACORD_126"].get("field_state") or gen["ACORD_126"]["mapped"]
    assert not s125.get("Policy_PolicyNumberIdentifier_A")
    assert s126.get("Insurer_FullName_A") in (None, "EMC Property & Casualty Company")
    assert s126.get("Insurer_NAICCode_A") in (None, "25186")
    assert (s126.get("Insurer_FullName_A"), s126.get("Insurer_NAICCode_A")) != \
        ("EMPLOYERS MUTUAL CASUALTY COMPANY", "25186")


def test_the_late_stamp_never_reopens_a_guard_blank(merged):
    mf, _docs = merged
    gen = _generated()
    gen["ACORD_126"]["guard_blanks"] = [{"field": "Insurer_FullName_A", "removed_value": "x"}]
    arq._backfill_and_resolve_present(gen, mf)
    state = gen["ACORD_126"].get("field_state") or gen["ACORD_126"]["mapped"]
    assert not state.get("Insurer_FullName_A")


def test_a_confirmed_policy_number_never_overwrites_a_section_header(merged):
    mf, _docs = merged
    gen = _generated()
    facts = {**mf, "policy_number": {"value": "6E7-40-02---26", "source": "user_confirmed"}}
    arq._restamp_canonical_into_forms(gen, "policy_number", facts)
    s126 = gen["ACORD_126"].get("field_state") or gen["ACORD_126"]["mapped"]
    assert s126["Policy_PolicyNumberIdentifier_A"] == "BBC7263 - 26"


# ── GAP FILL READS ITS OWN LINE'S PAGES ──────────────────────────────────────

def test_each_line_reads_its_own_pages_plus_the_unclaimed_ones(merged):
    mf, docs = merged
    scopes = ps.build_line_page_scopes(docs, mf)
    assert {"general_liab", "auto"} <= set(scopes)
    gl, auto = scopes["general_liab"], scopes["auto"]
    assert "General Liability Schedule" in gl and "TERRITORY: 104 6679" not in gl
    assert "TERRITORY: 104 6679" in auto and "General Liability Schedule" not in auto
    for scope in (gl, auto):
        assert "Coverages and Premium" in scope        # unclaimed common page
        assert "INSURER A" in scope                     # the certificate belongs to no page


def test_no_page_markers_means_no_scoping():
    assert ps.build_line_page_scopes([{"text": "plain text, no pages"}], {}) == {}


class _Recorder:
    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        user = next((m["content"] for m in kw.get("messages") or [] if m["role"] == "user"), "")
        self.calls.append(user)

        class _M:
            content = '{"values": {}, "raw_text_sourced": [], "question_grounding": {}}'

        class _C:
            message = _M()

        class _R:
            choices = [_C()]
            usage = None
        return _R()


def test_combined_gap_fill_sends_each_question_to_its_own_lines_pages(merged, monkeypatch):
    mf, docs = merged
    rec = _Recorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0)
    s126, s127 = _schema("ACORD_126"), _schema("ACORD_127")
    gl_f, auto_f = "GeneralLiability_Hazard_TerritoryCode_A", "Vehicle_Registration_StateOrProvinceCode_A"
    raw = "\n".join(d["text"] for d in docs)
    ps.combined_gap_fill({"ACORD_126": {gl_f: s126[gl_f]}, "ACORD_127": {auto_f: s127[auto_f]}},
                         mf, raw, line_scopes=ps.build_line_page_scopes(docs, mf))
    gl_calls = [u for u in rec.calls if gl_f in u]
    auto_calls = [u for u in rec.calls if auto_f in u]
    assert gl_calls and auto_calls
    assert all("TERRITORY: 104 6679" not in u for u in gl_calls)
    assert all("General Liability Schedule" not in u for u in auto_calls)


def test_without_scopes_the_whole_document_is_read(merged, monkeypatch):
    mf, docs = merged
    rec = _Recorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0)
    gl_f = "GeneralLiability_Hazard_TerritoryCode_A"
    raw = "\n".join(d["text"] for d in docs)
    ps.combined_gap_fill({"ACORD_126": {gl_f: _schema("ACORD_126")[gl_f]}}, mf, raw)
    assert any("TERRITORY: 104 6679" in u for u in rec.calls if gl_f in u)


# ── THE PROMPT ───────────────────────────────────────────────────────────────

def test_rule_16_defines_the_form_number_and_moved_to_v20():
    """A prompt edit that does not bump the version is served from the
    extraction cache and never reaches the model. v21 since the same day's
    coverage-basis definitions (improving-ll.md C89) - RULE 16 is unchanged."""
    assert es.PROMPT_VERSION == "v21"
    assert "A FORM number is never a policy number" in es._EXTRACT_PROMPT_PREFIX
    assert "never carry one over from another page or another line" in es._EXTRACT_PROMPT_PREFIX
