# -*- coding: utf-8 -*-
"""배포용 실행 파일에 넣을 아이콘(icon.ico)을 만든다. PyMuPDF 로 그리고 ICO 로 묶는다."""
from __future__ import annotations

import os
import struct

import pymupdf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
SIZES = (16, 24, 32, 48, 64, 128, 256)

BLUE = (0.184, 0.373, 0.816)      # #2f5fd0 - 화면의 강조색과 같은 색
DARKBLUE = (0.129, 0.278, 0.639)
WHITE = (1, 1, 1)
GREEN = (0.102, 0.498, 0.216)
LINE = (0.796, 0.843, 0.925)


def draw(size: int = 256) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=256, height=256)
    sh = page.new_shape()

    # 배경: 둥근 파란 사각형
    sh.draw_rect(pymupdf.Rect(6, 6, 250, 250), radius=0.22)
    sh.finish(fill=BLUE, color=DARKBLUE, width=2)

    # 문서: 흰 종이 + 접힌 모서리
    sh.draw_polyline([(66, 44), (150, 44), (192, 86), (192, 214), (66, 214), (66, 44)])
    sh.finish(fill=WHITE, color=None, closePath=True)
    sh.draw_polyline([(150, 44), (150, 86), (192, 86)])
    sh.finish(fill=LINE, color=None, closePath=True)

    # 본문 줄
    for i, y in enumerate((108, 130, 152, 174)):
        right = 172 if i % 2 == 0 else 156
        sh.draw_rect(pymupdf.Rect(86, y, right, y + 8))
        sh.finish(fill=LINE, color=None)

    # 확인 표시: 초록 원 + 흰 체크
    sh.draw_circle(pymupdf.Point(186, 190), 46)
    sh.finish(fill=GREEN, color=WHITE, width=7)
    sh.draw_polyline([(166, 190), (181, 206), (208, 173)])
    sh.finish(color=WHITE, width=15, closePath=False)

    sh.commit()
    pix = page.get_pixmap(matrix=pymupdf.Matrix(size / 256, size / 256), alpha=True)
    data = pix.tobytes("png")
    doc.close()
    return data


def build_ico(path: str = OUT) -> str:
    pngs = [(s, draw(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, png in pngs:
        w = h = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)
    return path


if __name__ == "__main__":
    p = build_ico()
    print("아이콘 생성:", p, os.path.getsize(p), "바이트")
