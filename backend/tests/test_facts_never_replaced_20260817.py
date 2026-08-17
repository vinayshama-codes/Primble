"""A session's facts must never be replaced wholesale when there is data to lose.

FOUND LIVE, 2026-08-17. The owner reported: two forms at SQS 68, package 67;
answered "no known losses" - a POSITIVE answer - and both forms fell to 23 and
the package to 37. Session `f50825ae` was inspected and held **one** fact
(`loss_history_years`) where a healthy session of the same package holds 71.
The facts had been destroyed, so there was nothing left to score.

The chain, two pieces each harmless alone:

  1. `_decrypt_facts` returned ``facts = None`` when the stored blob could not
     be decrypted - a deliberate choice so a key mismatch shows an empty session
     instead of crashing.
  2. The facts merge in `upd_processing_session` was additive ONLY when the
     existing value was a dict. ``None`` is not a dict, so the next write took
     the wholesale-replace branch and the entire fact set became whatever that
     write happened to carry - here, one fact from an ARQ answer.

Worse, `_encrypt_facts` short-circuits on a falsy value, so the substituted
``None`` was written back as ``null`` - destroying recoverable ciphertext on the
next write of ANY kind, including writes that never mentioned facts.

WHY THESE TESTS ARE PURE. The first version drove the real repository against
real rows and passed in isolation, then failed in the full suite: the suite
installs a STUB asyncpg (`test_arq_acord125_missing_only.py`) so it can run with
no database at all. A DB-bound test would also have failed in CI for everyone.
The decision itself was therefore extracted into `resolve_facts_write`, which is
pure - which is better code and permanently testable.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from repositories.session_repository import (                     # noqa: E402
    _FACTS_CIPHERTEXT_PRESERVED, _decrypt_facts, _encrypt_facts,
    resolve_facts_write,
)

# A blob with a valid envelope prefix and a payload no key can open - the exact
# shape of the two live sessions that lost their facts.
BROKEN_CIPHERTEXT = "enc:" + "A" * 120
GOOD_FACTS = {f"fact_{i}": f"value_{i}" for i in range(71)}
ONE_ARQ_ANSWER = {"loss_history_years": "5"}


def _undecryptable_session() -> dict:
    """A session as `upd_processing_session` sees it after a failed decrypt."""
    return _decrypt_facts({"session_id": "s1", "facts": BROKEN_CIPHERTEXT})


# ── the defect ───────────────────────────────────────────────────────────────

class TestUndecryptableFactsAreNeverDestroyed:

    def test_a_failed_decrypt_keeps_the_ciphertext(self):
        s = _undecryptable_session()
        assert s["facts"] is None, "readers must still see an empty session"
        assert s[_FACTS_CIPHERTEXT_PRESERVED] == BROKEN_CIPHERTEXT

    def test_the_arq_answer_that_caused_the_live_loss_is_refused(self):
        """THE REPORTED CASE: an answer carrying ONE fact must not become the
        entire fact set."""
        assert resolve_facts_write(_undecryptable_session(),
                                   ONE_ARQ_ANSWER) is None

    def test_the_ciphertext_is_written_back_byte_for_byte(self):
        """`_encrypt_facts` short-circuited on the substituted None and wrote
        facts=null, so even a write that never mentioned facts destroyed the
        blob."""
        out = _encrypt_facts(_undecryptable_session())
        assert out["facts"] == BROKEN_CIPHERTEXT
        assert _FACTS_CIPHERTEXT_PRESERVED not in out, "marker must not persist"

    def test_a_round_trip_through_decrypt_and_encrypt_changes_nothing(self):
        stored = {"session_id": "s1", "facts": BROKEN_CIPHERTEXT,
                  "tier2_score": 22}
        out = _encrypt_facts(_decrypt_facts(stored))
        assert out["facts"] == BROKEN_CIPHERTEXT
        assert out["tier2_score"] == 22, "the rest of the row must survive"

    def test_an_unreadable_non_dict_is_also_refused(self):
        """Belt and braces: a legacy / unparsed string with no preservation marker
        must not be replaced either."""
        assert resolve_facts_write({"facts": "some legacy string"},
                                   ONE_ARQ_ANSWER) is None

    def test_recovery_once_the_blob_is_readable_again(self):
        """The whole point of preserving it: when the key is corrected the data
        is still there and the normal additive merge resumes."""
        merged = resolve_facts_write({"facts": dict(GOOD_FACTS)}, ONE_ARQ_ANSWER)
        assert len(merged) == 72
        assert merged["loss_history_years"] == "5"


# ── everything that already worked must keep working ─────────────────────────

class TestTheHealthyPathIsUnchanged:

    def test_the_merge_is_additive(self):
        merged = resolve_facts_write({"facts": dict(GOOD_FACTS)}, ONE_ARQ_ANSWER)
        assert len(merged) == 72
        assert merged["fact_0"] == "value_0"

    def test_a_new_sessions_first_facts_write_still_lands(self):
        """The wholesale-replace branch is CORRECT when nothing is stored;
        narrowing it must not break session creation."""
        assert resolve_facts_write({}, {"applicant_name": "ORBIN"}) == \
            {"applicant_name": "ORBIN"}
        assert resolve_facts_write({"facts": None}, {"applicant_name": "ORBIN"}) == \
            {"applicant_name": "ORBIN"}
        assert resolve_facts_write({"facts": {}}, {"applicant_name": "ORBIN"}) == \
            {"applicant_name": "ORBIN"}

    @pytest.mark.parametrize("blank", [None, "", "   ", [], {}])
    def test_an_empty_value_still_cannot_blank_a_set_one(self, blank):
        """The pre-existing ARQ-vs-extraction race guard, re-pinned."""
        merged = resolve_facts_write({"facts": {"fact_0": "value_0"}},
                                     {"fact_0": blank})
        assert merged["fact_0"] == "value_0"

    def test_a_real_value_still_overwrites(self):
        merged = resolve_facts_write({"facts": {"fact_0": "old"}},
                                     {"fact_0": "new"})
        assert merged["fact_0"] == "new"

    def test_the_caller_dict_is_never_mutated(self):
        current = {"facts": {"a": "1"}}
        resolve_facts_write(current, {"b": "2"})
        assert current["facts"] == {"a": "1"}

    def test_a_healthy_blob_still_encrypts_normally(self):
        out = _encrypt_facts({"facts": {"a": "1"}})
        assert isinstance(out["facts"], str) and out["facts"] != '{"a": "1"}'
        assert _decrypt_facts(dict(out))["facts"] == {"a": "1"}

    def test_a_readable_blob_never_gains_the_marker(self):
        from utils.crypto import encrypt_field
        s = _decrypt_facts({"facts": encrypt_field(json.dumps({"a": "1"}))})
        assert s["facts"] == {"a": "1"}
        assert _FACTS_CIPHERTEXT_PRESERVED not in s
