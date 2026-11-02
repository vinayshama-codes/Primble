"""Brent, 2 Nov 2026: the beta bar on the home page and dashboard, and the policy
links at signup. Both signup doors must carry both links."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


def test_bar_prints_brents_wording():
    assert ("Primble is in Beta and welcomes new users. Additional features and upgrades publish weekly."
            in _read("components/layout/AnnouncementBar.jsx"))


def test_bar_shows_on_public_pages_and_the_dashboard_only():
    assert '(!(showModal && user) || modalStep === "dashboard") && <AnnouncementBar />' in _read("App.jsx")


def test_step_reaches_the_app_before_paint():
    assert "useLayoutEffect(() => { onStepChange?.(step); }, [step, onStepChange]);" in _read("components/form/AcordModal.jsx")
    assert "onStepChange={setModalStep}" in _read("App.jsx")


def test_dismissal_survives_blocked_storage():
    bar = _read("components/layout/AnnouncementBar.jsx")
    assert bar.count("try {") == 2 and bar.count("catch") == 2


def test_policy_urls_are_the_live_pages():
    constants = _read("config/constants.js")
    assert 'PRIVACY_POLICY_URL = "https://primble.com/privacy-policy"' in constants
    assert 'TERMS_OF_SERVICE_URL = "https://primble.com/terms-of-service"' in constants


def test_both_signup_doors_link_both_policies():
    for rel in ("components/auth/AuthModal.jsx", "components/auth/CompleteProfileModal.jsx"):
        src = _read(rel)
        assert "href={TERMS_OF_SERVICE_URL}" in src, rel
        assert "href={PRIVACY_POLICY_URL}" in src, rel
