# -*- coding: utf-8 -*-
"""RISS(학술연구정보서비스) 검색 결과 페이지를 읽어 서지 정보와 상세 페이지 링크를 얻는다.

RISS에는 공개 API가 없어 검색 결과 HTML을 파싱한다. 요청은 동시 2건으로 제한한다.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote, urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.riss.kr"
SEARCH_PATH = "/search/Search.do"

# 컬렉션 코드 (RISS 검색 탭)
COLS = {
    "re_a_kor": "국내학술논문",
    "bib_t": "학위논문",
    "re_a_over": "해외학술논문",
    "bib_m": "단행본",
    "re_t": "연구보고서",
}
MAT_TYPE_LABEL = {
    "1a0202e37d52c72d": "국내학술논문",
    "be54d9b8bc7cdb09": "학위논문",
    "3a11008f85f7c51d": "학술지",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
           "Accept": "text/html,application/xhtml+xml"}

_sem = asyncio.Semaphore(2)


@dataclass
class RissItem:
    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[str] = None
    publisher: Optional[str] = None
    container: Optional[str] = None     # 학술지명 / 학위구분
    volume: Optional[str] = None
    detail_url: str = ""
    control_no: str = ""
    mat_type: str = ""
    col: str = ""
    kci: Optional[str] = None           # KCI등재 / KCI등재후보
    fulltext: Optional[str] = None      # free | paid | yes | None
    permalink: Optional[str] = None     # https://www.riss.kr/link?id=A...
    doi: Optional[str] = None

    def to_dict(self):
        return asdict(self)


def search_url(query: str, col: str = "re_a_kor") -> str:
    params = {"isDetailSearch": "N", "searchGubun": "true", "queryText": "", "query": query, "colName": col}
    return BASE + SEARCH_PATH + "?" + urlencode(params, quote_via=quote)


def _txt(el) -> str:
    # 하이라이트 <span> 경계에 공백이 끼지 않도록 구분자 없이 이어붙인다
    return re.sub(r"\s+", " ", el.get_text("")).strip() if el else ""


def parse_search_html(html: str, col: str) -> list[RissItem]:
    soup = BeautifulSoup(html, "lxml")
    wrap = soup.select_one("div.srchResultListW")
    if wrap is None or wrap.select_one("div.noResultW"):
        return []
    items: list[RissItem] = []
    for li in wrap.select(":scope > ul > li"):
        cont = li.select_one("div.cont")
        if cont is None:
            continue
        a = cont.select_one("p.title a")
        if a is None:
            continue
        title = _txt(a)
        href = a.get("href", "")
        detail = urljoin(BASE, href.split("&keyword=")[0])
        m = re.search(r"control_no=([0-9a-f]+)", href)
        control_no = m.group(1) if m else ""
        m = re.search(r"p_mat_type=([0-9a-f]+)", href)
        mat_type = m.group(1) if m else ""
        etc = cont.select_one("p.etc")
        authors, year, publisher, container, volume = [], None, None, None, None
        if etc is not None:
            authors = [_txt(x) for x in etc.select("span.writer a")]
            if not authors:
                w = etc.select_one("span.writer")
                authors = [s.strip() for s in _txt(w).split(",") if s.strip()] if w else []
            pub = etc.select_one("span.assigned")
            publisher = _txt(pub) or None
            for sp in etc.find_all("span", recursive=False):
                if sp.get("class"):
                    continue
                t = _txt(sp)
                if re.fullmatch(r"\d{4}(?:\.\d{1,2})?", t):
                    year = t[:4]
                elif sp.find("a") and "p_mat_type=3a11008f85f7c51d" in (sp.find("a").get("href") or ""):
                    if container is None:
                        container = t
                    elif volume is None:
                        volume = t
                elif re.search(r"(국내|국외|해외)?\s*(석사|박사)", t):
                    container = t
        kci = None
        mk = li.select_one("div.markW img")
        if mk is not None and "KCI" in (mk.get("alt") or ""):
            kci = mk.get("alt")
        fulltext = None
        btn = li.select_one("div.btnW")
        if btn is not None and "원문보기" in _txt(btn):
            img = btn.select_one("img")
            alt = (img.get("alt") if img else "") or ""
            fulltext = "free" if "무료" in alt else ("paid" if "유료" in alt else "yes")
        items.append(RissItem(title, authors, year, publisher, container, volume, detail, control_no,
                              mat_type, col, kci, fulltext))
    return items


def parse_detail_html(html: str) -> dict:
    out: dict = {}
    m = re.search(r"https?://www\.riss\.kr/link\?id=([A-Z]\d+)", html)
    if m:
        out["permalink"] = "https://www.riss.kr/link?id=" + m.group(1)
    m = re.search(r'href="https?://(?:dx\.)?doi\.org/([^"\s]+)"', html)
    if m:
        out["doi"] = m.group(1)
    # 상세 페이지 제목은 "국문 제목 = English Title" 형태로 병기된다.
    # 검색 결과에는 국문만 나오므로, 영문으로 인용된 국내 문헌을 대조하려면 여기서 영문 제목을 얻어야 한다.
    m = re.search(r'<h3 class="title">(.*?)</h3>', html, re.S)
    if m:
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = (t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
             .replace("&quot;", '"').replace("&#034;", '"').replace("&#039;", "'").replace("&nbsp;", " "))
        t = re.sub(r"\s+", " ", t).strip()
        parts = [p.strip() for p in re.split(r"\s=\s", t) if p.strip()]
        if parts:
            out["title"] = parts[0]
            if len(parts) > 1:
                out["alt_titles"] = parts[1:]
    return out


async def search(client: httpx.AsyncClient, query: str, col: str = "re_a_kor") -> list[RissItem]:
    url = search_url(query, col)
    async with _sem:
        r = await client.get(url, headers=HEADERS, timeout=25.0, follow_redirects=True)
    r.raise_for_status()
    return parse_search_html(r.text, col)


async def detail(client: httpx.AsyncClient, detail_url: str) -> dict:
    async with _sem:
        r = await client.get(detail_url, headers=HEADERS, timeout=25.0, follow_redirects=True)
    r.raise_for_status()
    return parse_detail_html(r.text)
