"""The same document in one upload (owner's live check, 3 Nov 2026).

Two copies of one PDF dropped into the upload list were both kept, and the
server read, sent to the AI and merged both. Now the list refuses a file it
already holds (with a note), and the server reads identical files once.
"""
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from services import extraction_pipeline as ep

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(body, encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_list_refuses_a_file_it_already_holds(tmp_path):
    mod = (SRC / "utils" / "addDocuments.js").as_uri()
    out = _node(tmp_path, f"""
import {{ withoutDuplicateFiles, alreadyAddedNote }} from "{mod}";
const a = {{ name: "01_declarations_package.pdf", size: 39000, lastModified: 1 }};
const a2 = {{ name: "01_declarations_package.pdf", size: 39000, lastModified: 1 }};
const b = {{ name: "loss_runs.pdf", size: 12000, lastModified: 2 }};
const renamedOther = {{ name: "01_declarations_package.pdf", size: 41000, lastModified: 3 }};
console.log(JSON.stringify([
  withoutDuplicateFiles([a], [a2]).length,
  withoutDuplicateFiles([], [a, a2]).length,
  withoutDuplicateFiles([a], [b, renamedOther]).length,
  alreadyAddedNote([a], [a2]),
  alreadyAddedNote([a], [a2, a2, b]),
  alreadyAddedNote([a], [b]),
]));
""")
    assert out[0] == 1 and out[1] == 1
    assert out[2] == 3                                   # a different file of the same name is kept
    assert out[3] == "That file is already in the list, so it was not added again."
    assert out[4] == "2 files are already in the list, so they were not added again."
    assert out[5] == ""


def test_a_renamed_copy_is_refused_by_its_contents(tmp_path):
    mod = (SRC / "utils" / "addDocuments.js").as_uri()
    out = _node(tmp_path, f"""
import {{ withoutDuplicateFiles, alreadyAddedNote, fingerprintFiles }} from "{mod}";
const bytes = new TextEncoder().encode("%PDF-1.4 declarations page Orbin Contracting");
const original = new File([bytes], "01_declarations_package.pdf", {{ lastModified: 1 }});
const renamed  = new File([bytes], "copy of dec page.pdf",         {{ lastModified: 9 }});
const other    = new File([new TextEncoder().encode("%PDF-1.4 loss runs")], "loss.pdf", {{ lastModified: 2 }});
await fingerprintFiles([original]);
const list = withoutDuplicateFiles([], [original]);
await fingerprintFiles([renamed, other]);
console.log(JSON.stringify([
  withoutDuplicateFiles(list, [renamed]).length,
  withoutDuplicateFiles(list, [renamed, other]).map(f => f.name),
  alreadyAddedNote(list, [renamed]),
  withoutDuplicateFiles([], [renamed, renamed]).length,
]));
""")
    assert out[0] == 1                                   # same contents, different name: refused
    assert out[1] == ["01_declarations_package.pdf", "loss.pdf"]
    assert out[2] == "That file is already in the list, so it was not added again."
    assert out[3] == 1


def test_both_ways_of_adding_files_use_the_rule():
    src = (SRC / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    add = src[src.index("const addUploadFiles = async incoming => {"):]
    add = add[:add.index("};")]
    # Contents first (renamed copies too), then ONE merge that gives the list
    # and its note together, from the ref that is the list's source of truth
    # (review, 3 Nov 2026: the note was worked out apart from the merge).
    assert add.index("await fingerprintFiles(incoming)") < add.index("mergeUploadFiles(uploadListRef.current, incoming)")
    assert "setUploadFiles(merged.files)" in add and "setDupNote(merged.note)" in add
    assert "setFiles(prev =>" not in add
    drop = src[src.index("const handleDrop = e => {"):]
    drop = drop[:drop.index("};")]
    assert "addUploadFiles(uploaded)" in drop
    assert "addUploadFiles(picked)" in src
    assert "[...prev, ...Array.from(e.target.files)]" not in src
    assert "[...prev, ...uploaded]" not in src


def test_a_file_reading_like_one_already_read_is_a_duplicate_before_any_ai_call(monkeypatch):
    text = "DECLARATIONS PAGE - Named insured: Orbin Contracting LLC. Policy period 07/15/2026." * 3

    async def _read(path):
        return text, []

    def _no_ai(*a, **k):
        raise AssertionError("a duplicate must never reach the AI")

    monkeypatch.setattr(ep, "extract_text", _read)
    monkeypatch.setattr(ep, "classify_document", _no_ai, raising=False)
    out = asyncio.run(ep.extract_document("/tmp/x.pdf", "copy.pdf", "u1",
                                          known_texts={ep.document_text_key(text)}))
    assert out == {"duplicate": True, "filename": "copy.pdf", "text_key": ep.document_text_key(text)}


def test_the_fresh_upload_reads_identical_files_once(monkeypatch):
    seen_calls = []

    async def _fake_extract_document(path, name, user_id, *, reporter=None, index=0,
                                     doc_type=None, known_texts=None):
        seen_calls.append((name, known_texts is not None))
        text = "same text" if "copy" in name or name == "a.pdf" else "other text"
        key = ep.document_text_key(text)
        if known_texts is not None and key in known_texts:
            return {"duplicate": True, "filename": name, "text_key": key}
        return {"filename": name, "text": text, "low_confidence_tokens": []}

    finalized = {}

    async def _fake_finalize(docs, user_id, **kw):
        finalized["docs"] = [d["filename"] for d in docs]
        return {"ok": True}

    async def _no_presubmit(_paths):
        return None

    monkeypatch.setattr(ep, "extract_document", _fake_extract_document)
    monkeypatch.setattr(ep, "_finalize_pipeline", _fake_finalize)
    import services.acord_intake.transcriber_intake as ti
    monkeypatch.setattr(ti, "presubmit_package", _no_presubmit)

    asyncio.run(ep.run_extraction_pipeline(["/tmp/a.pdf", "/tmp/copy.pdf", "/tmp/b.pdf"], "u1"))
    assert finalized["docs"] == ["a.pdf", "b.pdf"]       # the copy is read once, not merged twice
    assert all(passed for _n, passed in seen_calls)      # every file is checked against those before it


# ═════════════════════════════════════════════════════════════════════════════
# The review of 3 Nov: one-step merge, one file hashed at a time, the server's
# read-once note
# ═════════════════════════════════════════════════════════════════════════════
def test_every_change_to_the_upload_list_goes_through_the_ref():
    src = (SRC / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    import re
    calls = re.findall(r"\bsetFiles\(", src)
    assert len(calls) == 1                              # only inside setUploadFiles
    assert "const setUploadFiles = next => { uploadListRef.current = next; setFiles(next); };" in src
    assert "onClick={() => removeUploadFile(i)}" in src
    assert src.count("clearUploadFiles();") >= 2       # reset + dashboard
    assert "uploadListRef.current = files;" not in src  # no render-time copy


def test_the_merge_and_its_note_come_from_one_step(tmp_path):
    mod = (SRC / "utils" / "addDocuments.js").as_uri()
    out = _node(tmp_path, f"""
import {{ mergeUploadFiles }} from "{mod}";
const a = {{ name: "a.pdf", size: 1, lastModified: 1 }};
const a2 = {{ name: "a.pdf", size: 1, lastModified: 1 }};
const b = {{ name: "b.pdf", size: 2, lastModified: 2 }};
const one = mergeUploadFiles([a], [a2, b]);
const none = mergeUploadFiles([], [a]);
const two = mergeUploadFiles([a, b], [a2, {{ ...b }}]);
console.log(JSON.stringify([one.files.map(f => f.name), one.note, none.note, two.files.length, two.note]));
""")
    assert out[0] == ["a.pdf", "b.pdf"]
    assert out[1] == "That file is already in the list, so it was not added again."
    assert out[2] == ""
    assert out[3] == 2 and out[4] == "2 files are already in the list, so they were not added again."


def test_files_are_hashed_one_at_a_time_and_big_ones_never(tmp_path):
    mod = (SRC / "utils" / "addDocuments.js").as_uri()
    out = _node(tmp_path, f"""
import {{ fingerprintFiles, withoutDuplicateFiles, FINGERPRINT_MAX_BYTES }} from "{mod}";
let reading = 0, most = 0, bigRead = false;
function fake(name, bytes, size) {{
  return {{ name, size: size ?? bytes.length, lastModified: 1,
    async arrayBuffer() {{
      if ((size ?? 0) > FINGERPRINT_MAX_BYTES) bigRead = true;
      reading += 1; most = Math.max(most, reading);
      await new Promise(r => setTimeout(r, 5));
      reading -= 1;
      return new TextEncoder().encode(bytes).buffer;
    }} }};
}}
const files = [fake("a.pdf", "same"), fake("b.pdf", "same"), fake("c.pdf", "other")];
const big1 = fake("big.pdf", "x", FINGERPRINT_MAX_BYTES + 1);
const big2 = fake("big copy.pdf", "x", FINGERPRINT_MAX_BYTES + 1);
await fingerprintFiles([...files, big1, big2]);
console.log(JSON.stringify([most, bigRead, FINGERPRINT_MAX_BYTES,
  withoutDuplicateFiles([], files).map(f => f.name),
  withoutDuplicateFiles([], [big1, big2]).length]));
""")
    assert out[0] == 1                                  # never two files in memory at once
    assert out[1] is False                              # a file over the cap is never read
    assert out[2] == 25 * 1024 * 1024
    assert out[3] == ["a.pdf", "c.pdf"]                 # a renamed copy found by contents
    assert out[4] == 2                                  # big files keep the name / size / time key


def test_the_read_once_note(tmp_path):
    mod = (SRC / "utils" / "addDocuments.js").as_uri()
    out = _node(tmp_path, f"""
import {{ readOnceNote }} from "{mod}";
console.log(JSON.stringify([readOnceNote(["dec copy.pdf"]), readOnceNote([]), readOnceNote(undefined),
  readOnceNote(["a.pdf", "b.pdf"])]));
""")
    assert out[0] == "dec copy.pdf is the same document as another file, so it was read once."
    assert out[1] == "" and out[2] == ""
    assert out[3] == "a.pdf and b.pdf are the same documents as other files, so each was read once."


def test_the_upload_screen_shows_the_servers_read_once_note():
    src = (SRC / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    up = src[src.index("const handleUpload = async () => {"):]
    up = up[:up.index("const handleResolveIntegrity")]
    assert "readOnceNote(data.duplicates_skipped)" in up


def test_the_upload_reports_each_file_it_read_once(monkeypatch):
    async def _fake_extract_document(path, name, user_id, *, reporter=None, index=0,
                                     doc_type=None, known_texts=None):
        text = "same text" if name in ("a.pdf", "a copy.pdf", "zip/a.pdf") else "other text"
        key = ep.document_text_key(text)
        if known_texts is not None and key in known_texts:
            return {"duplicate": True, "filename": name, "text_key": key}
        return {"filename": name, "text": text, "low_confidence_tokens": []}

    async def _fake_finalize(docs, user_id, **kw):
        return {"ok": True, "docs": [d["filename"] for d in docs]}

    sent = []

    async def _presubmit(paths, sent_paths=None):
        sent.append(list(paths))
        if sent_paths is not None:
            sent_paths.add(paths[0])
        return 1

    monkeypatch.setattr(ep, "extract_document", _fake_extract_document)
    monkeypatch.setattr(ep, "_finalize_pipeline", _fake_finalize)
    import services.acord_intake.transcriber_intake as ti
    monkeypatch.setattr(ti, "presubmit_package", _presubmit)
    out = asyncio.run(ep.run_extraction_pipeline(["/tmp/a.pdf", "/tmp/a copy.pdf", "/tmp/b.pdf"], "u1"))
    assert out["docs"] == ["a.pdf", "b.pdf"]
    assert out["duplicates_skipped"] == ["a copy.pdf"]


def test_the_upload_response_carries_the_files_read_once():
    import inspect
    from routes import form_routes as fr
    src = inspect.getsource(fr.upload_declaration)
    assert '"duplicates_skipped": list(pipeline_result.get("duplicates_skipped") or [])' in src


def test_the_pre_submit_never_sends_a_resaved_copy(tmp_path, monkeypatch):
    """A re-saved copy (other bytes, the same text) is not sent to ASG: the upload
    reads it once, as the earlier file, so its result would never be collected."""
    import services.acord_intake.transcriber_intake as TI
    from types import SimpleNamespace as NS

    class _Cfg:
        live = True
        env = "test"

    pages = [NS(page=0, kind="acord", form_id="ACORD_125", acord_number="125", edition="2016/03",
                text="ACORD 125 (2016/03) Page 1 of 4 - Orbin Contracting")]
    other = [NS(page=0, kind="acord", form_id="ACORD_126", acord_number="126", edition="2016/09",
                text="ACORD 126 (2016/09) Page 1 of 4 - Orbin Contracting")]
    by_path = {"a.pdf": pages, "a resaved.pdf": pages, "b.pdf": other}
    submitted = []

    class _Client:
        async def submit_only(self, data, **kw):
            submitted.append(data)
            return f"req_{len(submitted)}"

    import services.acord_intake.recognize as RZ
    import services.acord_intake.primble_record as PR
    import repositories.transcriber_repository as TR
    monkeypatch.setattr(TI, "load_config", lambda: _Cfg())
    monkeypatch.setattr(TI, "_default_client", lambda: _Client())
    monkeypatch.setattr(RZ, "recognize", lambda path: by_path[os.path.basename(path)])
    monkeypatch.setattr(PR, "carries_record", lambda path: False)
    monkeypatch.setattr(TI, "plan", lambda path, rec, **kw: NS(hash=f"h:{os.path.basename(path)}", pages=[0],
                                                             data=os.path.basename(path), input_format="pdf",
                                                             label="125"))
    monkeypatch.setattr(TI, "_spend", lambda n: True)

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(TR, "get_cached", _none)
    monkeypatch.setattr(TR, "put_cached", _none)
    paths = [str(tmp_path / n) for n in ("a.pdf", "a resaved.pdf", "b.pdf")]
    sent_paths = set()
    n = asyncio.run(TI.presubmit_package(paths, sent_paths=sent_paths))
    assert n == 2 and sorted(submitted) == ["a.pdf", "b.pdf"]
    assert sent_paths == {paths[0], paths[2]}           # the LIST's first copy, whatever finishes first
