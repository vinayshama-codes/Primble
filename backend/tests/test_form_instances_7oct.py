"""Form instances (7 Oct 2026, Choice Electric #4): the id rule every layer shares."""
import glob
import os

import pytest

from services import form_instances as fi

_HERE = os.path.dirname(__file__)


def test_no_base_form_id_contains_the_separator():
    names = [os.path.basename(p) for p in glob.glob(os.path.join(_HERE, "..", "forms_schemas", "*.json"))]
    names += [os.path.basename(p) for p in glob.glob(os.path.join(_HERE, "..", "templates", "*.pdf"))]
    assert names, "schemas / templates not found"
    assert not [n for n in names if fi.SEPARATOR in n]


@pytest.mark.parametrize("fid,base,key,label,stem", [
    ("ACORD_131", "ACORD_131", None, "ACORD 131", "ACORD_131"),
    ("ACORD_137_CO", "ACORD_137_CO", None, "ACORD 137 CO", "ACORD_137_CO"),
    ("ACORD_131__excess", "ACORD_131", "excess", "ACORD 131 (Excess)", "ACORD_131_Excess"),
    ("ACORD_131__excess-2", "ACORD_131", "excess-2", "ACORD 131 (Excess 2)", "ACORD_131_Excess2"),
])
def test_ids_split_and_label(fid, base, key, label, stem):
    assert fi.base_form_id(fid) == base
    assert fi.instance_key(fid) == key
    assert fi.is_instance(fid) is (key is not None)
    assert fi.instance_label(fid) == label
    assert fi.file_stem(fid) == stem


@pytest.mark.parametrize("bad", ["", None, "ACORD_131__", "__excess", "ACORD_131__Excess",
                                 "ACORD_131__1x", "ACORD_131__ex cess"])
def test_malformed_ids_are_not_instances(bad):
    assert not fi.is_instance(bad)
    assert fi.base_form_id(bad) == str(bad or "")


def test_make_instance_id_refuses_nesting_and_bad_keys():
    assert fi.make_instance_id("ACORD_131", "excess") == "ACORD_131__excess"
    with pytest.raises(ValueError):
        fi.make_instance_id("ACORD_131__excess", "excess")
    with pytest.raises(ValueError):
        fi.make_instance_id("ACORD_131", "Excess")


def test_plain_form_facts_are_the_same_object():
    facts = {"umbrella_limit": "$5,000,000"}
    assert fi.facts_for_form(facts, "ACORD_131") is facts
    assert fi.facts_for_form(facts, "ACORD_125") is facts


def test_an_instance_without_a_provider_or_with_a_failing_one_keeps_the_facts():
    facts = {"x": 1}
    assert fi.facts_for_form(facts, "ACORD_999__excess") is facts
    saved = dict(fi._OVERLAYS)
    try:
        fi.register_overlay("ACORD_999", lambda f, k: 1 / 0)
        assert fi.facts_for_form(facts, "ACORD_999__excess") is facts
        fi.register_overlay("ACORD_999", lambda f, k: dict(f, layer=k))
        assert fi.facts_for_form(facts, "ACORD_999__excess") == {"x": 1, "layer": "excess"}
    finally:
        fi._OVERLAYS.clear()
        fi._OVERLAYS.update(saved)
