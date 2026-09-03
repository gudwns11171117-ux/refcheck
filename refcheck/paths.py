# -*- coding: utf-8 -*-
"""소스로 실행할 때와 exe로 실행할 때의 경로 차이를 한곳에서 흡수한다.

exe(PyInstaller 단일 파일)로 묶이면 프로그램 파일들은 임시 폴더에 풀렸다가 종료 시 지워진다.
따라서 읽기 전용 자원(static)은 임시 폴더에서 찾고, 캐시처럼 남겨야 하는 것은 사용자 폴더에 쓴다.
"""
from __future__ import annotations

import os
import sys

APP_NAME = "RefCheck"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _source_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """static/index.html 처럼 프로그램에 딸려 오는 읽기 전용 파일의 경로."""
    base = getattr(sys, "_MEIPASS", None) or _source_root()
    return os.path.join(base, *parts)


def data_dir() -> str:
    """캐시처럼 실행 뒤에도 남겨야 하는 파일을 두는 쓰기 가능한 폴더."""
    if is_frozen():
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, APP_NAME)
    return _source_root()


def cache_dir() -> str:
    return os.path.join(data_dir(), "cache")
