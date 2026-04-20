import re
import hashlib
import logging

logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """
    Pre-LLM text cleaning pipeline.
    1. Fix encoding artifacts
    2. Kill page markers and bare line numbers
    3. Collapse whitespace
    4. Deduplicate repeated paragraphs (headers/footers)
    """
    try:
        import ftfy
        text = ftfy.fix_text(text)
    except ImportError:
        pass  # ftfy optional

    # Kill page markers: "Page 3 of 12", "- 3 -", bare digits on own line
    text = re.sub(r'\bPage\s+\d+\s+of\s+\d+\b', '', text, flags=re.I)
    text = re.sub(r'^\s*-\s*\d+\s*-\s*$', '', text, flags=re.M)
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.M)

    # Kill ALL-CAPS boilerplate legal lines (>8 words, all caps)
    def is_boilerplate(line):
        words = line.strip().split()
        return len(words) > 8 and sum(1 for w in words if w.isupper()) / len(words) > 0.8
    text = '\n'.join(line for line in text.splitlines() if not is_boilerplate(line))

    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # Deduplicate paragraphs
    seen: set = set()
    out = []
    for para in text.split('\n\n'):
        stripped = para.strip()
        if len(stripped) < 10:
            continue
        h = hashlib.md5(stripped.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append(stripped)

    return '\n\n'.join(out)


def table_rows_to_text(tables: list) -> str:
    """Convert extracted table list to LLM-readable text block."""
    if not tables:
        return ""
    parts = []
    for tbl in tables:
        page = tbl.get("page", "?")
        rows = tbl.get("rows", [])
        if not rows:
            continue
        header = " | ".join(str(c) for c in (rows[0] or []))
        body = "\n".join(" | ".join(str(c or "") for c in row) for row in rows[1:])
        parts.append(f"[TABLE page={page}]\n{header}\n{body}\n[/TABLE]")
    return "\n\n".join(parts)
