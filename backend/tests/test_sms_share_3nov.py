"""SMS sharing - "Text the link" (3 Nov 2026, frontend/src/utils/smsShare.js): the producer's own Messages app
opens with the client's questionnaire link typed. No provider, no server change."""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
UTIL = FRONT / "utils" / "smsShare.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_number_message_and_link(tmp_path):
    script = tmp_path / "s.mjs"
    script.write_text(
        f"import * as S from {json.dumps(UTIL.as_uri())};\n"
        "const nums = ['(303) 555-0142', '1-303-555-0142', '+44 20 7946 0958', '555-0142', '', null,"
        " '0123456789', '+1 303 555 0142 ext 9', '303-555-0142 x12', '(303) 555-0142 #7', '+44 (0)20 7946 0958']"
        ".map(S.smsNumber);\n"
        "const link = 'https://primble.ai/questionnaire/' + 'a'.repeat(64);\n"
        "const msg = S.smsMessage({ clientName: '  Erin  Royal ', link });\n"
        "const anon = S.smsMessage({ clientName: '', link });\n"
        "console.log(JSON.stringify({ nums, msg, anon, href: S.smsHref('(303) 555-0142', msg), none: S.smsHref('', 'a b&c') }));\n",
        encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["nums"][:5] == ["+13035550142", "+13035550142", "+442079460958", "", ""]
    assert o["nums"][5] == "" and o["nums"][6] == ""            # nothing / an impossible US number: Messages asks
    assert o["nums"][7:10] == ["+13035550142"] * 3               # an extension is never dialled into the number
    assert o["nums"][10] == "+442079460958"                      # nor a trunk "(0)"
    assert o["msg"].startswith("Hi Erin, please answer your insurance questions here: ") and o["msg"].endswith("a" * 64)
    assert o["anon"].startswith("Please answer your insurance questions here: ")
    assert len(o["msg"]) <= 160                                  # one SMS segment for a normal name
    assert o["href"].startswith("sms:+13035550142?&body=Hi%20Erin")
    assert o["none"] == "sms:?&body=a%20b%26c"


def test_both_send_screens_offer_it():
    page = (FRONT / "components" / "form" / "review" / "QuestionnairePage.jsx").read_text(encoding="utf-8")
    # the phone on file only when the questionnaire goes to the contact on file (hard review, 3 Nov 2026)
    assert 'phone: toEmail.toLowerCase() === String(onFile.email || "").trim().toLowerCase() ? onFile.phone : ""' in page
    assert "smsHref(result.phone, smsMessage({ clientName: result.name, link: result.link }))" in page   # from the send
    assert "data.email_sent === false" in page
    assert "Text the link" in page
    modal = (FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    assert 'href={smsHref("", smsMessage({ clientName, link: sent.link }))}>Text the link</a>' in modal
    assert "if (res.ok && data.success) { if (data.link) setSent({ link: data.link, data }); else onSuccess(data); }" in modal
    assert "sent.data.email_sent === false" in modal              # the sent step says when the e-mail did not go
    q = (FRONT / "utils" / "questionnaire.js").read_text(encoding="utf-8")
    assert 'phone: pick("A.1g", "contact_phone")' in q
    for f in (UTIL, FRONT / "components" / "auth" / "TurnstileWidget.jsx"):
        assert "—" not in f.read_text(encoding="utf-8")       # no em-dash in UI text
