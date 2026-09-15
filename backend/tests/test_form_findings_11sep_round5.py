"""11 Sep 2026, round 5: an address LINE TWO that repeats its own block.

Live run 3, every interest block on both runs: LineOne `800 Walnut Street`,
LineTwo `800 Walnut St`; Run B printed the city `Boulder` on line two. A
third-party address has no fact, so each component is its own gap-fill answer
and the model re-used a piece of the address it had already written.
"""
import re

import pytest

import services.pdf_service as ps

AI = "AdditionalInterest_MailingAddress_"


def _block(row="A", root=AI, **parts):
    return {f"{root}{k}_{row}": v for k, v in parts.items()}


DES_MOINES = dict(CityName="Des Moines", StateOrProvinceCode="IA", PostalCode="50309")
BOULDER = dict(CityName="Boulder", StateOrProvinceCode="CO", PostalCode="80302")


class TestTheLiveCases:
    def test_the_street_printed_twice(self):
        m = _block(LineOne="800 Walnut Street", LineTwo="800 Walnut St", **DES_MOINES)
        assert list(ps._line_two_repeats_its_block(m)) == [f"{AI}LineTwo_A"]

    def test_the_city_on_line_two(self):
        m = _block(LineOne="1600 Broadway", LineTwo="Boulder", **BOULDER)
        assert list(ps._line_two_repeats_its_block(m)) == [f"{AI}LineTwo_A"]

    @pytest.mark.parametrize("two", ["Boulder, CO 80302", "Boulder CO", "80302",
                                     "CO", "Boulder, Colorado 80302-1234"])
    def test_the_locality_on_line_two(self, two):
        m = _block(LineOne="1600 Broadway", LineTwo=two, **BOULDER)
        if "Colorado" in two:
            # State NAMES are not folded here - "colorado" is not a word of
            # the block, so the box is kept. Conservative by design.
            assert not ps._line_two_repeats_its_block(m)
        else:
            assert list(ps._line_two_repeats_its_block(m)) == [f"{AI}LineTwo_A"]

    def test_the_unit_already_on_line_one(self):
        """The 2026-09-06 `Ste 300` twice, in a block nothing owns."""
        m = _block(LineOne="2255 Shorebank Ave, Ste 300", LineTwo="Suite 300",
                   CityName="Tacoma", StateOrProvinceCode="WA", PostalCode="98402")
        assert list(ps._line_two_repeats_its_block(m)) == [f"{AI}LineTwo_A"]


class TestARealLineTwoIsKept:
    @pytest.mark.parametrize("one,two", [
        ("100 Main St", "Suite 100"),              # suite number == street number
        ("5 Main St", "5"),                        # a bare number is never judged
        ("300 Shorebank Ave", "300"),
        ("800 Walnut Street", "Suite 5"),
        ("800 Walnut Street", "Attn: Loan Servicing"),
        ("800 Walnut Street", "800 Walnut Street, Suite 5"),   # carries MORE
        ("12 Box Elder Rd", "PO Box 12"),          # words present, order not
        ("4800 Dahlia St", "# D13"),
        ("Walnut Street", "Walnut Plaza"),
        ("1 Boulder Way", "Boulder Tower"),        # a city word plus a real one
    ])
    def test_kept(self, one, two):
        m = _block(LineOne=one, LineTwo=two, **BOULDER)
        assert not ps._line_two_repeats_its_block(m), (one, two)

    def test_rows_are_judged_separately(self):
        m = {**_block("A", LineOne="800 Walnut Street", **DES_MOINES),
             **_block("B", LineOne="1600 Broadway", LineTwo="800 Walnut Street", **BOULDER)}
        assert not ps._line_two_repeats_its_block(m)

    def test_blocks_are_judged_separately(self):
        m = {**_block(LineOne="800 Walnut Street", **DES_MOINES),
             **_block(root="CertificateHolder_MailingAddress_",
                      LineOne="1600 Broadway", LineTwo="800 Walnut Street")}
        assert not ps._line_two_repeats_its_block(m)

    @pytest.mark.parametrize("junk", [None, "", "   ", 0, [], {}, "—", "\x00"])
    def test_junk_never_raises(self, junk):
        m = _block(LineOne=junk, LineTwo=junk, CityName=junk)
        ps._line_two_repeats_its_block(m)


def test_every_line_two_in_every_schema_is_in_a_judged_block():
    """Harvested, so a new address root cannot land outside the rule."""
    missed = []
    for fid, sch in ps._all_form_schemas().items():
        for f in sch:
            if re.search(r"_LineTwo_[A-Z]$", f):
                m = ps._ADDRESS_BLOCK_PART_RE.match(f)
                if not m or f.replace("_LineTwo_", "_LineOne_") not in sch:
                    missed.append((fid, f))
    assert missed == []


def test_through_the_post_fill_seam():
    """The guard is only real if `_enforce_post_fill_guards` runs it."""
    schema = ps._all_form_schemas()["ACORD_125"]
    ps._set_schema_context(schema)
    mapped = {"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc.",
              **_block(LineOne="800 Walnut Street", LineTwo="800 Walnut St", **DES_MOINES)}
    before = dict(mapped)
    facts = {"_form_id": "ACORD_125", "applicant_name": "Orbin Contracting LLC",
             "mailing_address": "4800 Dahlia St, Denver, CO 80216"}
    ps._enforce_post_fill_guards(mapped, schema, facts, gpt_filled_set=set(mapped))
    assert not mapped.get(f"{AI}LineTwo_A")
    for k, v in before.items():
        if k != f"{AI}LineTwo_A":
            assert mapped.get(k) == v, k


class TestZipPlusFour:
    """A ZIP+4 is the same delivery point as its ZIP5 - both directions."""

    def test_zip_plus_four_on_line_two(self):
        m = _block(LineOne="1600 Broadway", LineTwo="80302-1234", **BOULDER)
        assert list(ps._line_two_repeats_its_block(m)) == [f"{AI}LineTwo_A"]

    def test_zip_plus_four_in_the_postal_box(self):
        m = _block(LineOne="1600 Broadway", LineTwo="Boulder 80302",
                   CityName="Boulder", StateOrProvinceCode="CO", PostalCode="80302-1234")
        assert list(ps._line_two_repeats_its_block(m)) == [f"{AI}LineTwo_A"]

    def test_a_different_zip_is_kept(self):
        m = _block(LineOne="1600 Broadway", LineTwo="80303", **BOULDER)
        assert not ps._line_two_repeats_its_block(m)


def test_no_control_characters_in_the_guard_source():
    """The first cut of this guard shipped a BACKSPACE where a regex word
    boundary belonged (a patch-script escape collapsed), and every other test
    still passed. Pin the source."""
    import inspect
    src = inspect.getsource(ps._address_words) + inspect.getsource(ps._line_two_repeats_its_block)
    assert not [c for c in src if ord(c) < 32 and c not in "\n\t"]
