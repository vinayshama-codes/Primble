"""Suite-wide environment defaults.

GAP_FILL_TEXT_SELECTION defaults to OFF in production (owner decision
2026-08-12: LLM call 2 reads the COMPLETE document). The text-selection tests
exercise the filter itself, so the suite opts in here - conftest runs before
any test module imports the service, and setting a concrete value (not
absence) is what lets the kill-switch tests save/restore it safely.
`test_the_production_default_is_whole_document` pins the production default.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")
os.environ.setdefault("GAP_FILL_TEXT_SELECTION", "1")
