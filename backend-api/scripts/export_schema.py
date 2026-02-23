#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models import RunSpec


def main() -> None:
    out_dir = ROOT / "schema"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "runspec.schema.json"
    schema = RunSpec.model_json_schema()
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
