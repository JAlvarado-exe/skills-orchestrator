"""Read JSON the way Windows tools write it: UTF-8 with or without a byte order mark."""
from __future__ import annotations

import json


def read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)
