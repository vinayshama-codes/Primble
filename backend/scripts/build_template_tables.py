"""Precompute the tables read off the ACORD template PDFs (6 Oct 2026).

Writes templates/template_tables.json - see services/template_tables.py. Run it
after a template PDF or one of the two readers changes; until then the readers
simply read the PDF live (a stale table is never used).

    py backend/scripts/build_template_tables.py      (from the repo root)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import logging  # noqa: E402
logging.disable(logging.WARNING)

from config.settings import TEMPLATE_DIR  # noqa: E402
from services import template_tables as tt  # noqa: E402
from services.pdf_service import (  # noqa: E402
    PRINTED_CURRENCY_READER_VERSION, _read_fields_with_printed_currency,
)
from services.state_restricted_boxes import (  # noqa: E402
    READER_VERSION as STATE_READER_VERSION, read_restricted_boxes,
)


def main() -> None:
    forms = sorted(f[:-4] for f in os.listdir(TEMPLATE_DIR) if f.lower().endswith(".pdf"))
    currency, states = {}, {}
    for fid in forms:
        sha = tt.template_sha(fid)
        currency[fid] = {"sha": sha, "version": PRINTED_CURRENCY_READER_VERSION,
                         "data": sorted(_read_fields_with_printed_currency(fid))}
        states[fid] = {"sha": sha, "version": STATE_READER_VERSION,
                       "data": {k: sorted(v) for k, v in sorted(read_restricted_boxes(fid).items())}}
        print(f"{fid}: {len(currency[fid]['data'])} '$' boxes, {len(states[fid]['data'])} state boxes")
    out = {"about": "Precomputed by scripts/build_template_tables.py - see services/template_tables.py",
           "tables": {"printed_currency_fields": currency, "state_restricted_boxes": states}}
    with open(tt.tables_path(), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote", tt.tables_path())


if __name__ == "__main__":
    main()
