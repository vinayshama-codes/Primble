"""Live package 8aa8f3ad (30 Oct 2026, run-4 Ridgeline dec): three defects."""
from services import extraction_service as E
from services import sqs_service as Q

CUR = [{"line": "Commercial General Liability", "policy_number": "CGL-4471209-25",
        "effective_date": "12/01/2025", "expiration_date": "12/01/2026"}]


# 1. A VIN that is not 17 characters is a warning (a wrapped table cell dropped
#    the last character of three VINs and nothing said so).
def test_short_vin_is_named_and_warned():
    f = {"auto_vin_schedule": [{"vin": "1FTBR1C82PKA41827", "year": "2023"},
                               {"vin": "3C6LRVDG4NE11836", "year": "2022"},
                               {"vin": "1GCZGHFP5", "year": "1975"},          # pre-1981: no standard VIN
                               {"vin": "", "year": "2024"}]}
    assert Q.vehicles_with_bad_vin(f) == ["2"]
    hard, soft = Q.evaluate_stops({**f, "has_auto_coverage": True}, {"has_auto_coverage": True})
    assert any(m.startswith("Vehicle VIN incomplete") for m in soft)


def test_good_vins_and_bad_input_raise_nothing():
    assert Q.vehicles_with_bad_vin({"auto_vin_schedule": [{"vin": "1FTBR1C82PKA41827"}]}) == []
    assert Q.vehicles_with_bad_vin({}) == [] and Q.vehicles_with_bad_vin({"auto_vin_schedule": "x"}) == []


# 2. "RENEWAL of policy X" dates X as the term that ended when the current began.
def test_renewed_policy_gets_the_preceding_term():
    f = {"prior_coverage_by_line": [{"line": "Commercial General Liability", "policy_no": "CGL-4471209-24"}],
         "coverage_lines": CUR}
    assert E.date_renewed_policies(f, [{"text": "Transaction RENEWAL of policy CGL-4471209-24"}])
    row = f["prior_coverage_by_line"][0]
    assert (row["effective"], row["expiration"]) == ("12/01/2024", "12/01/2025")


def test_no_declaration_no_date_and_stated_dates_kept():
    f = {"prior_coverage_by_line": [{"line": "Commercial General Liability", "policy_no": "CGL-4471209-24"}],
         "coverage_lines": CUR}
    assert not E.date_renewed_policies(f, [{"text": "benefits on renewal of this policy"}])
    assert not E.date_renewed_policies(f, [{"text": "RENEWAL of policy CGL-4471209-24", "excluded": True}])
    g = {"prior_coverage_by_line": [{"line": "Commercial General Liability", "policy_no": "CGL-4471209-24",
                                     "effective": "06/01/2024", "expiration": "12/01/2025"}], "coverage_lines": CUR}
    assert not E.date_renewed_policies(g, [{"text": "RENEWAL of policy CGL-4471209-24"}])
    assert g["prior_coverage_by_line"][0]["effective"] == "06/01/2024"
    assert not E.date_renewed_policies(None, None)


# 3. One undated policy no longer unkeys the 125 prior grid.
def test_an_undated_policy_does_not_unkey_the_grid():
    from services.pdf_service import _prior_coverage_grid_build
    rows = [{"line": l, "carrier": c, "policy_no": f"{p}-{y}", "effective": f"12/01/20{y}",
             "expiration": f"12/01/20{int(y) + 1}"}
            for l, c, p in [("Commercial General Liability", "Summit", "CGL-1"), ("Business Auto", "Front", "BAP-1")]
            for y in ("21", "22")]
    rows.append({"line": "Workers Compensation", "carrier": "Pinnacle", "policy_no": "WC-9-24"})
    grid, years = _prior_coverage_grid_build({"prior_coverage_by_line": rows})
    assert years == ["2022", "2021"]
    aside = [e.get("policy_no") for e in grid.set_aside]
    assert "WC-9-24" in aside
    assert not any(str(n).startswith(("CGL-1", "BAP-1")) for n in aside)


# 4. Live 50a7d9e6: a form's proposed effective date beside the dec's CURRENT-term
#    expiration made a backwards term. The form's date takes its expiration with it.
def test_a_forms_effective_date_takes_its_expiration_when_the_pair_is_impossible():
    f = {"effective_date": {"value": "12/01/2026", "source": "acord_form"},
         "expiration_date": {"value": "12/01/2026", "source": "ai"},
         "prior_effective_date": "12/01/2024", "prior_expiration_date": "12/01/2025"}
    assert E.follow_proposed_expiration(f)
    assert f["expiration_date"]["value"] == "12/01/2027"
    # a document's own (even odd) pair, a valid pair, and a person's expiration are never touched
    g = {"effective_date": {"value": "12/01/2026", "source": "ai"},
         "expiration_date": {"value": "12/01/2026", "source": "ai"},
         "prior_effective_date": "12/01/2024", "prior_expiration_date": "12/01/2025"}
    assert not E.follow_proposed_expiration(g)
    h = dict(f, expiration_date={"value": "12/01/2027", "source": "ai"})
    assert not E.follow_proposed_expiration(h)
    p = dict(f, expiration_date={"value": "12/01/2026", "source": "producer"})
    assert not E.follow_proposed_expiration(p)


def test_a_zero_length_document_term_takes_the_renewal_expiration():
    """CH125 live 7a85b6dd: the dec read 12/01/2026 into both proposed dates; the
    prior term 12/01/2025-12/01/2026 ends on that effective date, so the
    expiration is one term later, derived."""
    from services.extraction_service import follow_proposed_expiration
    env = lambda v: {"value": v, "source": "ai", "confidence": "ai_high"}
    f = {"effective_date": env("12/01/2026"), "expiration_date": env("12/01/2026"),
         "prior_effective_date": env("12/01/2025"), "prior_expiration_date": env("12/01/2026")}
    assert follow_proposed_expiration(f)
    assert f["expiration_date"]["value"] == "12/01/2027" and f["expiration_date"]["source"] == "derived"
    # No continuity (the prior term ends elsewhere): left alone, the warning asks.
    g = {"effective_date": env("12/01/2026"), "expiration_date": env("12/01/2026"),
         "prior_effective_date": env("06/01/2024"), "prior_expiration_date": env("06/01/2025")}
    assert not follow_proposed_expiration(g) and g["expiration_date"]["value"] == "12/01/2026"
    # A person's expiration is never touched.
    h = {"effective_date": env("12/01/2026"),
         "expiration_date": {"value": "12/01/2026", "source": "producer", "confidence": "filled"},
         "prior_effective_date": env("12/01/2025"), "prior_expiration_date": env("12/01/2026")}
    assert not follow_proposed_expiration(h)


def test_a_package_policy_takes_its_lines_box_beside_a_second_policy():
    """Policy-by-line kit: GL 2026 held the package policy and a project GL; both
    went to ACORD 101 while the package number printed under Property - one
    policy twice. The package contract takes the GL box; only the other is listed."""
    from services.pdf_service import _prior_coverage_grid_build
    rows = [
        {"line": "General Liability", "carrier": "Quillon P&C", "policy_no": "QPC5519-26",
         "effective": "01/01/2026", "expiration": "01/01/2027", "premium": "$5,000"},
        {"line": "Property", "carrier": "Quillon P&C", "policy_no": "QPC5519-26",
         "effective": "01/01/2026", "expiration": "01/01/2027", "premium": "$5,000"},
        {"line": "General Liability", "carrier": "Lakeside Specialty", "policy_no": "LSG-4471102-26",
         "effective": "01/01/2026", "expiration": "01/01/2027", "premium": "$900"},
    ]
    grid, years = _prior_coverage_grid_build({"prior_coverage_by_line": rows})
    gl = [e for (c, _r), e in grid.items() if c == "GeneralLiability"]
    assert gl and gl[0]["policy_no"] == "QPC5519-26"
    aside = [e["policy_no"] for e in getattr(grid, "set_aside", ())]
    assert aside == ["LSG-4471102-26"]
