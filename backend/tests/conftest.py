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
# The narrative reader (services/narrative_reader) makes a model call on every
# narrative save; the suite runs offline. Its own tests stub the call.
os.environ.setdefault("NARRATIVE_READER", "0")
# The carrier narrative writer (services/questionnaire, improving-ll.md C110)
# makes a model call per draft; the suite runs offline and its tests stub it.
os.environ.setdefault("CARRIER_NARRATIVE", "0")
# ASG Transcriber (services/asg_transcriber): OFF in the suite, and even a test
# that turns it on answers from the saved stub replies - the suite never
# reaches ASG (owner, 29 Oct 2026: no live call without permission; usage is
# metered per page).
os.environ.setdefault("TRANSCRIBER", "0")
os.environ.setdefault("TRANSCRIBER_STUB_DIR",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "transcriber_stub"))
