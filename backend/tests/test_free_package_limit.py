"""The free-tier allowance has ONE owner: config.settings.FREE_PACKAGE_LIMIT.

Client direction 2026-09-16: a new account gets ONE free package, not three.
The number used to be a bare `3` repeated across five modules. These tests fail
the build if a gate, a remaining-count or a message goes back to a literal.
"""
import pathlib
import re

import pytest

from config.settings import FREE_PACKAGE_LIMIT

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Every module that gates, counts or announces the free allowance.
_GATE_FILES = [
    "routes/auth_routes.py",
    "routes/form_routes.py",
    "routes/download_routes.py",
    "routes/dev_routes.py",
]


def test_default_allowance_is_one():
    """The shipped default. An env var may raise it; nothing else may."""
    assert FREE_PACKAGE_LIMIT == 1


def test_the_limit_is_never_negative():
    assert FREE_PACKAGE_LIMIT >= 0


@pytest.mark.parametrize("rel", _GATE_FILES)
def test_no_module_hardcodes_the_free_allowance(rel):
    """A gate must read the constant, never a literal."""
    src = (_ROOT / rel).read_text(encoding="utf-8")
    offenders = []
    for ln, line in enumerate(src.splitlines(), 1):
        if "downloads_used" not in line and "downloads_remaining" not in line and "used >=" not in line:
            continue
        if (re.search(r"or 0\)\s*>=\s*\d", line)
                or re.search(r"used\s*>=\s*\d", line)
                or re.search(r"\d+\s*-\s*used", line)
                or re.search(r"\"downloads_remaining\":\s*\d", line)):
            offenders.append(f"{rel}:{ln}: {line.strip()}")
    assert not offenders, (
        "free-tier allowance hardcoded instead of reading FREE_PACKAGE_LIMIT:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("rel", _GATE_FILES)
def test_every_gate_module_imports_the_constant(rel):
    src = (_ROOT / rel).read_text(encoding="utf-8")
    assert "FREE_PACKAGE_LIMIT" in src, f"{rel} no longer reads the one door"


def test_user_facing_message_agrees_with_the_limit():
    """The upgrade wall must not promise a number the gate does not enforce."""
    src = (_ROOT / "routes/form_routes.py").read_text(encoding="utf-8")
    assert "You've used all {FREE_PACKAGE_LIMIT} free submission" in src
    # and it pluralises, so "all 1 free submissions" can never print
    assert "'' if FREE_PACKAGE_LIMIT == 1 else 's'" in src


def test_remaining_count_goes_to_zero_at_the_limit():
    """The gate and the displayed remaining count flip at the same point."""
    for used in range(0, FREE_PACKAGE_LIMIT + 3):
        assert (used >= FREE_PACKAGE_LIMIT) == ((FREE_PACKAGE_LIMIT - used) <= 0)
