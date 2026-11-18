"""Read JSON the way Windows tools write it: UTF-8 with or without a byte order mark."""
from __future__ import annotations

import json
import os
import tempfile
import time


def read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json_atomic(path: str, data, indent=None) -> None:
    """Publish one complete document even when multiple processes write to the same file."""
    payload = json.dumps(data, indent=indent, ensure_ascii=True)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False)
    try:
        with temp:
            temp.write(payload)
        for attempt in range(6):
            try:
                os.replace(temp.name, path)
                return
            except PermissionError as exc:
                # Windows readers can briefly prevent replacement by another process.
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        try:
            os.unlink(temp.name)
        except FileNotFoundError:
            pass
