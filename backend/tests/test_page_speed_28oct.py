"""28 Oct 2026: the pre-form page took 43 s on Orbin (re-uploaded forms + decs) -
the review plan re-scores the same package dozens of times, and four pure readers
re-parsed the same strings each time (normalize_date's 47 strptime formats was 27 s
of it). They are cached now (page 6-7 s, same score and items). The caches must
change no answer and hand every caller its own mutable result."""
from services import lob_canon, normalization as nz


def test_normalize_date_answers_are_unchanged():
    cases = {"07/15/25": "2025-07-15", "7/15/2025": "2025-07-15", "2025-07-15": "2025-07-15",
             "July 15th, 2025": "2025-07-15", "15-Jul-2025": "2025-07-15", " 07/15/2025 ": "2025-07-15",
             "abc": None, "": None, None: None, "Policy Period": None, 12345678: None}
    for _ in range(2):                                  # cold, then cached
        for v, want in cases.items():
            assert nz.normalize_date(v) == want, v


def test_canon_line_cache_keeps_non_strings_and_answers():
    for _ in range(2):
        assert lob_canon.canon_line("Commercial General Liability") == lob_canon._canon_line("Commercial General Liability")
        assert lob_canon.canon_line("Excess GL") == lob_canon._canon_line("Excess GL")
    assert lob_canon.canon_line(None) is None


def test_entity_menus_give_each_caller_its_own_sets():
    text = "Entity: [X] LLC  [ ] Corporation  [ ] Partnership"
    first = nz._entity_menus(text)
    assert first == nz._entity_menus_uncached(text)
    if first:
        first[0]["families"].add("poisoned"); first[0]["marked"].add("poisoned")
    again = nz._entity_menus(text)
    assert all("poisoned" not in m["families"] and "poisoned" not in m["marked"] for m in again)
    assert again == nz._entity_menus_uncached(text)
