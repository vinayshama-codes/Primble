"""PACKAGE checks vs FORM checks (owner, 30 Oct 2026).

Every cross_form_validator code has a scope; a form-scope check is never on the
pre-form screen and never holds the package; a package-scope check keeps holding
the package, reads without form numbers before forms and offers its data fix only.
"""
from services import cross_form_validator as cfv
from services import issue_registry as reg


def test_every_validator_code_has_a_scope():
    codes = cfv.rule_codes()
    assert len(codes) > 40, "harvester read nothing"
    declared = reg.FORM_SCOPE_CODES | reg.PACKAGE_SCOPE_CODES
    missing = sorted(c for c in codes if c not in declared)
    assert not missing, f"cross-form codes with no package/form scope: {missing}"
    assert not (reg.FORM_SCOPE_CODES & reg.PACKAGE_SCOPE_CODES)


def test_scope_table_names_only_real_codes():
    codes = cfv.rule_codes()
    stale = sorted(c for c in reg.FORM_SCOPE_CODES if c not in codes)
    assert not stale, stale
    stale = sorted(c for c in reg.PACKAGE_SCOPE_CODES
                   if c not in codes and not c.startswith("legacy_"))
    assert not stale, stale


def test_legacy_application_minimum_is_package():
    code = reg.classify_legacy("ACORD 125 minimum field missing: Producer", "soft")[0]
    assert reg.issue_scope(code) == "package"


def _issue(code, msg, forms, add=None, t="soft_warning"):
    return cfv._issue(t, code, msg, forms, add_forms=add)


def test_defer_form_scope_only():
    form = _issue("contractor_missing_acord186", "Add ACORD 186.", ["ACORD_126", "ACORD_186"], ["ACORD_186"])
    loc = _issue("location_count_mismatch_minor", "ACORD 125 lists 2 location(s) but ACORD 140 has 1.",
                 ["ACORD_125", "ACORD_140"])
    pkg = _issue("wc_payroll_vs_revenue", "WC payroll is 90% of total revenue.",
                 ["ACORD_125", "ACORD_130"], ["ACORD_101"])
    out = cfv.defer_form_choices([form, loc, pkg])
    assert out[0]["form_choice"] and out[0]["type"] == "advisory" and out[0]["deferred_type"] == "soft_warning"
    assert out[1]["form_choice"] and out[1]["type"] == "advisory"
    assert out[2] is pkg            # package scope stays a stop, add_forms or not
    hard, soft, _adv = cfv.split_cross_form_issues(out)
    assert soft == [pkg["message"] + " (Affects: ACORD 125, ACORD 130. Fix: Review the coverage/limit "
                    "details for the affected form(s).)"]


def test_pre_form_view_wording_and_no_form_cards():
    pkg = _issue("auto_um_uim_not_specified", "UM/UIM coverage is not specified on ACORD 127.",
                 ["ACORD_127"])
    pkg2 = _issue("wc_payroll_vs_revenue", "WC payroll is 90% of total revenue.",
                  ["ACORD_125", "ACORD_130"], ["ACORD_101"])
    loc = _issue("location_count_mismatch_minor", "ACORD 125 lists 2 location(s) but ACORD 140 has 1.",
                 ["ACORD_125", "ACORD_140"])
    msgs = [pkg["message"], pkg2["message"], loc["message"]]
    view = reg.build_grouped_view([], [], msgs, cross_issues=[pkg, pkg2, loc])
    before = reg.pre_form_view(view)
    items = [it for t in before["warnings"].values() for c in t for it in c["items"]]
    by_code = {it["code"]: it for it in items}
    assert "location_count_mismatch_minor" not in by_code
    assert by_code["auto_um_uim_not_specified"]["message"].startswith("Auto: ")
    assert "ACORD" not in by_code["auto_um_uim_not_specified"]["message"]
    assert by_code["wc_payroll_vs_revenue"]["message"].startswith("Workers Comp: ")
    assert "add_forms" not in (by_code["wc_payroll_vs_revenue"].get("resolution") or {})
    # issue_id unchanged, stored view untouched
    assert by_code["auto_um_uim_not_specified"]["issue_id"] == pkg["issue_id"]
    after = [it for t in view["warnings"].values() for c in t for it in c["items"]]
    assert any(it["code"] == "location_count_mismatch_minor" for it in after)
    assert any(it["message"] == pkg["message"] for it in after)
    assert before["counts"]["warnings"] == view["counts"]["warnings"] - 1


def test_form_scope_holds_only_its_named_forms():
    from services.sqs_service import _form_open_warning
    form = cfv.defer_form_choices([_issue("contractor_missing_acord186", "Add ACORD 186.",
                                          ["ACORD_126", "ACORD_186"], ["ACORD_186"])])
    assert _form_open_warning("ACORD_126", {}, {}, {}, {}, {}, form) == "Add ACORD 186."
    assert _form_open_warning("ACORD_127", {}, {}, {}, {}, {}, form) is None
