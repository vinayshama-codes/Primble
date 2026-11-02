"""Billing screens for live Stripe (2 Nov 2026).

"Change Plan" / "Upgrade" for a user who already paid opened a SECOND full-price
subscription. The server now refuses a second checkout (409 subscription_exists /
payment_due, 503 when Stripe is down); the screens never start one for a paying
user, show the server's words, and offer Manage billing where paying fixes it.
Billing e-mails link to /?open=billing, which opens Manage billing once.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
_BILLING = SRC / "utils" / "billing.js"
_STRIPE_API = SRC / "api" / "stripeApi.js"


def _read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


def _frontend_sources():
    for path in SRC.rglob("*"):
        if path.suffix in (".js", ".jsx") and path.is_file():
            yield path, path.read_text(encoding="utf-8")


def _body(src, start, end_marker="\n  };\n"):
    """The text of one function, from its declaration to its closing brace."""
    i = src.index(start)
    return src[i:src.index(end_marker, i)]


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(body, encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ── B1: no paying user starts a checkout ─────────────────────────────────────
def test_one_door_calls_create_checkout():
    callers = [p.relative_to(SRC).as_posix() for p, s in _frontend_sources() if "/api/stripe/create-checkout" in s]
    assert callers == ["api/stripeApi.js"]


def test_every_checkout_caller_is_gated_on_a_paid_plan():
    callers = sorted(p.relative_to(SRC).as_posix() for p, s in _frontend_sources()
                     if "startCheckout(" in s and p != _STRIPE_API)
    assert callers == ["App.jsx", "components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx"]

    app = _body(_read("App.jsx"), "const triggerPendingCheckout = async (forUser) => {")
    assert app.index("if (hasPaidPlan(forUser))") < app.index("startCheckout(")
    for rel in ("components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx"):
        src = _read(rel)
        assert "const subscribed = hasPaidPlan(user);" in src, rel
        handler = _body(src, "const handleSelect = async (planId) => {")
        assert handler.index("if (subscribed) return;") < handler.index("startCheckout("), rel


def test_sign_in_callbacks_pass_the_account_that_signed_in():
    app = _read("App.jsx")
    assert "triggerPendingCheckout(usr)" in app
    assert "triggerPendingCheckout(u)" in app
    assert "triggerPendingCheckout(user)" in app
    assert "triggerPendingCheckout()" not in app


def test_paying_users_see_current_plan_and_the_support_note():
    billing = _BILLING.read_text(encoding="utf-8")
    assert 'SUPPORT_EMAIL = "support@primble.ai"' in billing
    assert "CHANGE_PLAN_NOTE = `To change your plan, contact ${SUPPORT_EMAIL}.`" in billing

    header = _read("components/layout/Header.jsx")
    assert not re.search(r">\s*Change Plan\s*<", header)      # no button opens the plan cards
    assert "onChangePlan" not in header
    panel = header[header.index("function InlinePlanPanel("):header.index("function UserDropdown(")]
    assert "Current plan" in panel and "{CHANGE_PLAN_NOTE}" in panel and "Manage billing" in panel

    for rel in ("components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx"):
        src = _read(rel)
        assert "Current plan" in src, rel
        assert 'return "Upgrade"' not in src, rel      # never a downgrade or same plan labelled Upgrade
    # The plan-change note shows in the account dropdown and the upgrade window,
    # never on the home page's plan section (owner, 2 Nov 2026).
    assert "<PlanChangeNote openBillingPortal={openBillingPortal}" in _read("components/billing/UpgradeModal.jsx")
    assert "<PlanChangeNote" not in _read("components/pages/PricingPage.jsx")
    # A paying user's other plans: a greyed-out button that cannot be clicked
    # (owner, 2 Nov 2026), on the home page and in the upgrade window alike.
    for rel in ("components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx"):
        src = _read(rel)
        i = src.index("Contact support to change")
        assert "disabled" in src[i - 600:i] and "not-allowed" in src[i - 600:i], rel
        assert "Contact support to switch" not in src, rel

    note = _read("components/billing/PlanChangeNote.jsx")
    assert "{CHANGE_PLAN_NOTE}" in note and "Manage billing" in note


def test_no_upgrade_promise_to_a_paying_user():
    modal = _read("components/billing/UpgradeModal.jsx")
    assert '{subscribed ? "No long-term contracts. Cancel anytime." :' in modal


def test_has_paid_plan(tmp_path):
    out = _node(tmp_path, f"""
import {{ hasPaidPlan }} from {json.dumps(_BILLING.as_uri())};
console.log(JSON.stringify([null, {{}}, {{ subscription_tier: "free" }}, {{ subscription_tier: "essentials" }},
  {{ subscription_tier: "professional", payment_status: "canceling" }}, {{ subscription_tier: "business" }}].map(hasPaidPlan)));
""")
    assert out == [False, False, False, True, True, True]


# ── 409 / 503 from create-checkout, 400 from the portal ──────────────────────
def test_server_messages_are_read_from_either_detail_shape(tmp_path):
    out = _node(tmp_path, f"""
import * as B from {json.dumps(_BILLING.as_uri())};
const exists = {{ detail: {{ code: "subscription_exists", message: "You already have an active Primble plan. To change your plan, contact support@primble.ai." }} }};
const due = {{ detail: {{ code: "payment_due", message: "Your last payment didn't go through. Update your card in Manage billing to restore your plan." }} }};
const portal = {{ detail: {{ code: "no_billing_account", message: "There's no billing account to manage yet." }} }};
console.log(JSON.stringify({{
  msgs: [exists, due, portal, {{ detail: "plain" }}, {{ detail: [{{ loc: 1 }}] }}, null].map((d) => B.apiErrorMessage(d, "fallback")),
  codes: [exists, due, portal, {{ detail: "plain" }}, null].map(B.apiErrorCode),
  fix: ["payment_due", "subscription_exists", null].map(B.needsBillingFix),
}}));
""")
    assert out["msgs"] == [
        "You already have an active Primble plan. To change your plan, contact support@primble.ai.",
        "Your last payment didn't go through. Update your card in Manage billing to restore your plan.",
        "There's no billing account to manage yet.",
        "plain", "fallback", "fallback",
    ]
    assert out["codes"] == ["subscription_exists", "payment_due", "no_billing_account", None, None]
    assert out["fix"] == [True, False, False]


def test_start_checkout_returns_the_servers_words(tmp_path):
    src = _STRIPE_API.read_text(encoding="utf-8")
    src = src.replace('import { API_BASE } from "../config/constants";', 'const API_BASE = "";')
    src = src.replace('from "../utils/billing";', f"from {json.dumps(_BILLING.as_uri())};")
    module = tmp_path / "stripeApi.mjs"
    module.write_text(src, encoding="utf-8")
    out = _node(tmp_path, f"""
const replies = [
  [200, {{ checkout_url: "https://checkout.example/x" }}],
  [409, {{ detail: {{ code: "subscription_exists", message: "You already have an active Primble plan. To change your plan, contact support@primble.ai." }} }}],
  [409, {{ detail: {{ code: "payment_due", message: "Your last payment didn't go through. Update your card in Manage billing to restore your plan." }} }}],
  [503, {{ detail: "Billing is temporarily unavailable. Please try again shortly." }}],
  [503, null],
];
let i = 0;
globalThis.fetch = async () => {{
  const [status, body] = replies[i++];
  return {{ ok: status < 400, status, json: async () => {{ if (body === null) throw new Error("no json"); return body; }} }};
}};
const {{ startCheckout }} = await import({json.dumps(module.as_uri())});
const out = [];
for (let k = 0; k < replies.length; k++) out.push(await startCheckout("professional", "monthly"));
globalThis.fetch = async () => {{ throw new Error("offline"); }};
out.push(await startCheckout("professional", "monthly"));
console.log(JSON.stringify(out));
""")
    assert out[0] == {"url": "https://checkout.example/x"}
    assert out[1] == {"code": "subscription_exists",
                      "message": "You already have an active Primble plan. To change your plan, contact support@primble.ai."}
    assert out[2]["code"] == "payment_due"
    assert out[3] == {"code": None, "message": "Billing is temporarily unavailable. Please try again shortly."}
    assert out[4]["code"] is None and "try again" in out[4]["message"]
    assert out[5] == {"code": None, "message": "Network error. Please try again."}


def test_payment_due_offers_manage_billing_and_no_spinner_sticks():
    note = _read("components/billing/PlanChangeNote.jsx")
    err = note[note.index("export function CheckoutError("):]
    assert "{error.message}" in err and "needsBillingFix(error.code) && openBillingPortal" in err

    for rel in ("components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx"):
        src = _read(rel)
        handler = _body(src, "const handleSelect = async (planId) => {")
        tail = handler[handler.index("startCheckout("):]
        assert "setLoadingPlan(null);" in tail and "setCheckoutError(result);" in tail, rel
        assert "<CheckoutError error={checkoutError} openBillingPortal={openBillingPortal}" in src, rel

    app = _read("App.jsx")
    pending = _body(app, "const triggerPendingCheckout = async (forUser) => {")
    assert "setPortalRedirecting(false);" in pending[pending.index("startCheckout("):]
    assert "needsBillingFix(result.code) ? { message: result.message, billing: true }" in pending
    assert "{headerError.billing && (" in app


def test_no_object_detail_is_rendered_raw():
    app = _read("App.jsx")
    portal = _body(app, "const openBillingPortal = async () => {")
    assert 'apiErrorMessage(data, "Could not open billing portal.")' in portal
    assert "data.detail ||" not in portal
    for rel in ("App.jsx", "components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx"):
        assert "data.detail || \"Failed to start checkout" not in _read(rel), rel


# ── The retired overage pack ──────────────────────────────────────────────────
def test_nothing_calls_the_removed_overage_endpoints():
    for path, src in _frontend_sources():
        for gone in ("create-overage-checkout", "apply-overage", "applyOverage", "overage_paid"):
            assert gone not in src, (path.name, gone)


# ── ?open=billing from the billing e-mails ───────────────────────────────────
def test_open_billing_is_read_once_and_removed_from_the_url():
    app = _read("App.jsx")
    billing = _BILLING.read_text(encoding="utf-8")
    assert 'OPEN_BILLING_PARAM = "billing"' in billing
    init = app[app.index("const [billingIntent, setBillingIntent] = useState(() => {"):]
    init = init[:init.index("\n  });\n")]
    assert 'url.searchParams.get("open") === OPEN_BILLING_PARAM' in init
    assert 'url.searchParams.delete("open");' in init
    assert "window.history.replaceState(" in init
    # sessionStorage carries it through sign-in, and blocked storage never throws.
    assert init.count("try {") == 2 and init.count("catch") == 2
    assert "sessionStorage.setItem(OPEN_BILLING_KEY" in init


def test_open_billing_opens_the_portal_once_and_never_loops():
    app = _read("App.jsx")
    effect = app[app.index("    if (!billingIntent || authLoading) return;"):]
    effect = effect[:effect.index("}, [billingIntent, authLoading, user]);")]
    # Signed out: ask for sign-in once and keep the intent.
    signed_out = effect[effect.index("if (!user) {"):effect.index("if (billingOpenedRef.current) return;")]
    assert "billingSignInAskedRef.current = true;" in signed_out and "setShowAuthModal(true);" in signed_out
    # Signed in: the intent is cleared BEFORE the portal opens.
    assert effect.index("billingOpenedRef.current = true;") < effect.index("dropBillingIntent();") < effect.index("openBillingPortal();")
    drop = app[app.index("const dropBillingIntent = () => {"):]
    drop = drop[:drop.index("\n  };\n")]
    assert "try { sessionStorage.removeItem(OPEN_BILLING_KEY); } catch" in drop
    assert "setBillingIntent(false);" in drop
    # Closing the sign-in window drops the intent.
    assert "onClose={() => { setShowAuthModal(false); if (billingIntent) dropBillingIntent(); }}" in app


# ── L2: an archived account is restored by paying ────────────────────────────
def test_archived_banner_offers_billing_not_support():
    modal = _read("components/form/AcordModal.jsx")
    line = next(l for l in modal.splitlines() if 'if (ps === "archived") return' in l)
    assert "Account archived -" in line and "onClick={onOpenBillingPortal}" in line
    assert "Update billing</button>" in line and "to restore access." in line
    assert "mailto:support@primble.ai" not in line

    block = next(l for l in modal.splitlines() if "const blockMsg = " in l)
    assert '["Account archived - ", "Update billing", " to restore access."]' in block
    upload = modal[modal.index("{uploadBlocked && ("):]
    upload = upload[:upload.index("{/* Drop zone card */}")]
    assert "onClick={onOpenBillingPortal}" in upload and "{blockMsg[1]}" in upload
    assert "Account archived. Contact support." not in modal

    header = _read("components/layout/Header.jsx")
    badge = header[header.index('if (user.payment_status === "archived") return ('):]
    badge = badge[:badge.index('if (user.payment_status === "suspended")')]
    assert "onClick={openBillingPortal}" in badge and "Update billing" in badge
    assert "mailto:" not in badge


# ── L8: overage is counted per package (per score on Essentials) ─────────────
def test_overage_banner_names_what_is_counted():
    modal = _read("components/form/AcordModal.jsx")
    assert "each additional download will be billed" not in modal
    assert ('each additional {user?.subscription_tier === "essentials" ? "score" : "package"} '
            "will be billed on your next invoice.") in modal


def test_no_em_dash_in_the_new_billing_copy():
    for rel in ("utils/billing.js", "components/billing/PlanChangeNote.jsx", "api/stripeApi.js"):
        assert "—" not in _read(rel), rel
    for rel in ("App.jsx", "components/billing/UpgradeModal.jsx", "components/pages/PricingPage.jsx",
                "components/layout/Header.jsx"):
        src = _read(rel)
        for needle in ("CHANGE_PLAN_NOTE", "Contact support to change", "Current plan", "Update billing"):
            for m in re.finditer(re.escape(needle), src):
                assert "—" not in src[m.start() - 80:m.end() + 80], (rel, needle)
