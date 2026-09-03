# -*- coding: utf-8 -*-
"""외부 조회 결과를 디스크에 잠시 저장한다(같은 논문을 다시 검사할 때 네트워크를 다시 타지 않게)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Optional

from .paths import cache_dir

CACHE_DIR = cache_dir()
TTL_SEC = 30 * 24 * 3600


def _path(key: str) -> str:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h[:2], h + ".json")


def get(key: str) -> Optional[Any]:
    p = _path(key)
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if time.time() - obj.get("_t", 0) > TTL_SEC:
            return None
        return obj.get("v")
    except (OSError, ValueError):
        return None


def put(key: str, value: Any) -> None:
    p = _path(key)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"_t": time.time(), "v": value}, f, ensure_ascii=False)
    except OSError:
        pass
