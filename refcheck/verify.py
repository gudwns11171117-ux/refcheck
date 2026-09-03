# -*- coding: utf-8 -*-
"""참고문헌 항목이 실제로 존재하는지 Crossref·OpenAlex·RISS로 확인하고 링크를 만든다.

논문 심사에 쓰는 도구이므로 판정을 보수적으로 한다.
가짜를 '확인됨'으로 통과시키는 쪽이 위험하고, 진짜를 '확인 불가'로 넘기는 쪽은 사람이 한 번 더 보면 되는 실수다.
그래서 확실한 증거(제목·연도·저자 또는 DOI)가 모이지 않으면 '확인됨'을 주지 않는다.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional
from urllib.parse import quote

import httpx
from rapidfuzz import fuzz

from . import cache, riss
from .parse import (KOREA_HINT_RE, ParsedRef, norm_for_match, parse_reference)

UA = "RefCheck/1.0 (local reference verification tool)"
API_HEADERS = {"User-Agent": UA, "Accept": "application/json"}
CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"

_sem_crossref = asyncio.Semaphore(3)
_sem_openalex = asyncio.Semaphore(3)
_sem_web = asyncio.Semaphore(4)


class LookupFailed(Exception):
    """조회 자체가 실패한 경우. '찾지 못함'과 반드시 구분해야 한다.

    심사 도구에서 통신 실패가 조용히 '확인 불가'로 바뀌면 없는 근거를 만든 셈이 된다.
    """


# 하루 한도를 넘겼거나 접속이 막힌 조회처. 한 번 걸리면 그 회차에는 더 두드리지 않는다.
# (OpenAlex 는 무료 일일 한도가 있어 소진되면 429 와 함께 budget 안내를 준다.)
_unavailable: dict[str, str] = {}


def reset_sources() -> None:
    _unavailable.clear()


def unavailable_sources() -> dict[str, str]:
    return dict(_unavailable)

# 후보를 화면에 '확인된 서지'로 보여 줄 최소 제목 유사도. 이보다 낮으면 남남으로 본다.
SHOW_FLOOR = 65.0
STRONG_SIM = 88.0      # 이 이상이면 더 뒤지지 않고 멈춘다
STRONG_SCORE = 0.80

STATUS_LABEL = {
    "verified": "확인됨",
    "likely": "검토 필요",
    "unverified": "확인 불가",
    "skipped": "검증 제외",
    "error": "오류",
}
KIND_LABEL = {
    "article": "학술논문", "thesis": "학위논문", "book": "단행본", "report": "보고서/기관자료",
    "law": "법령", "web": "웹자료", "unknown": "미분류",
}


@dataclass
class Candidate:
    source: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[str] = None
    container: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    extra: dict = field(default_factory=dict)
    score: float = 0.0
    title_sim: float = 0.0
    year_ok: Optional[bool] = None
    author_ok: Optional[bool] = None
    container_ok: Optional[bool] = None
    alt_titles: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d.pop("alt_titles", None)
        return d


@dataclass
class RefResult:
    ref: dict
    status: str
    status_label: str
    kind_label: str
    best: Optional[dict]
    candidates: list[dict]
    links: list[dict]
    note: str
    elapsed: float
    flags: list[str] = field(default_factory=list)   # 심사자가 눈으로 확인해야 할 지점
    sources: list[str] = field(default_factory=list)  # 실제로 조회한 곳

    def to_dict(self):
        return asdict(self)


@dataclass
class Options:
    # 전수조사(exhaustive)가 켜져 있으면 확실한 일치가 없을 때 어떤 문헌이든 RISS까지 넓혀 다시 찾는다.
    # riss_all 은 처음부터 RISS를 함께 조회할지의 문제라, 기본값을 꺼 두어도 놓치지 않는다.
    riss_all: bool = False
    check_urls: bool = True
    strict: bool = True           # 엄격 판정을 기본으로
    exhaustive: bool = True       # 확실한 일치가 없으면 컬렉션·질의를 넓혀 계속 찾는다
    openalex_key: str = ""        # 무료 키를 넣으면 OpenAlex 하루 한도가 10배($0.1 -> $1)


# ---------------------------------------------------------------- 점수
def _sim(ref: ParsedRef, c: Candidate) -> float:
    raw_n = norm_for_match(ref.raw)
    best = 0.0
    for t in [c.title] + list(c.alt_titles):
        ct = norm_for_match(t)
        if not ct:
            continue
        s = 0.0
        rt = norm_for_match(ref.title) if ref.title else ""
        if rt:
            s = max(fuzz.token_set_ratio(rt, ct), fuzz.ratio(rt, ct))
            # 길이가 크게 다르면 token_set_ratio 가 과대평가되므로 억제한다
            if len(ct) < 0.6 * len(rt) or len(rt) < 0.6 * len(ct):
                s = min(s, fuzz.ratio(rt, ct) + 15)
        # 제목 추출이 어긋났을 때를 대비해 원문 전체와도 대본다.
        # 짧은 후보 제목이 우연히 걸리지 않도록 길이 조건을 둔다.
        min_len = max(20, int(0.6 * len(rt))) if rt else 24
        if len(ct) >= min_len and len(ct.split()) >= 3:
            s = max(s, fuzz.partial_ratio(ct, raw_n) * 0.95)
        best = max(best, s)
    return best


def score_candidate(ref: ParsedRef, c: Candidate) -> None:
    c.title_sim = round(_sim(ref, c), 1)
    if ref.year and c.year and str(c.year).isdigit():
        c.year_ok = abs(int(ref.year) - int(c.year)) <= 1
    if ref.first_author and c.authors:
        fa = norm_for_match(ref.first_author)
        names = " ".join(norm_for_match(a) for a in c.authors)
        c.author_ok = bool(fa) and (fa in names or any(fa in norm_for_match(a) for a in c.authors))
    if ref.container and c.container:
        a, b = norm_for_match(ref.container), norm_for_match(c.container)
        if a and b:
            c.container_ok = max(fuzz.token_set_ratio(a, b), fuzz.partial_ratio(a, b)) >= 80
    score = c.title_sim / 100 * 0.72
    score += 0.15 if c.year_ok else (0.06 if c.year_ok is None else -0.12)
    score += 0.10 if c.author_ok else (0.04 if c.author_ok is None else -0.08)
    score += 0.05 if c.container_ok else (0.02 if c.container_ok is None else -0.02)
    c.score = round(max(0.0, min(1.0, score)), 3)


def _is_strong(c: Candidate) -> bool:
    return c.title_sim >= STRONG_SIM and c.score >= STRONG_SCORE


def decide(best: Optional[Candidate], strict: bool, doi_confirmed: bool) -> tuple[str, list[str], bool]:
    """(판정, 심사자가 확인할 지점, 후보를 화면에 보여 줄지)를 낸다."""
    if best is None:
        return "unverified", [], False
    mismatch = [name for name, ok in (("연도 불일치", best.year_ok),
                                      ("저자 불일치", best.author_ok),
                                      ("게재지 불일치", best.container_ok)) if ok is False]

    if doi_confirmed and best.title_sim >= 85:
        return "verified", mismatch, True
    if strict:
        # 엄격: 제목이 거의 같고, 연도가 맞고, 저자나 게재지 중 하나가 뒷받침되어야 '확인됨'
        if best.title_sim >= 92 and best.year_ok and (best.author_ok or best.container_ok):
            return "verified", mismatch, True
        if best.title_sim >= 96 and best.year_ok and best.author_ok is None and best.container_ok is None:
            return "verified", mismatch, True
    else:
        if best.score >= 0.80 and best.title_sim >= 85:
            return "verified", mismatch, True
    # 학술 논문 제목은 상투어가 많아 유사도가 부풀기 쉽다.
    # 제목만 어중간하게 닮았는데 연도·저자·게재지가 둘 이상 어긋나면 남의 논문으로 본다.
    if len(mismatch) >= 2 and best.title_sim < 95:
        return "unverified", [], False
    if best.title_sim >= 70:
        return "likely", mismatch, True
    return "unverified", mismatch if best.title_sim >= SHOW_FLOOR else [], best.title_sim >= SHOW_FLOOR


# ---------------------------------------------------------------- 외부 조회
async def _get_json(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore, source: str = "") -> dict:
    """실패하면 LookupFailed 를 올린다. 조용히 빈 결과를 돌려주지 않는다."""
    key = "json:" + url
    hit = cache.get(key)
    if hit is not None:
        return hit
    if source and source in _unavailable:
        raise LookupFailed(f"{source} {_unavailable[source]}")
    last = ""
    for attempt in range(3):
        async with sem:
            try:
                r = await client.get(url, timeout=25.0, headers=API_HEADERS)
            except httpx.HTTPError as e:
                last = type(e).__name__
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
        if r.status_code == 404:
            cache.put(key, {"_404": True})
            return {"_404": True}
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                raise LookupFailed("응답이 JSON 형식이 아님")
            cache.put(key, data)
            return data
        last = f"HTTP {r.status_code}"
        if r.status_code == 429:
            body = r.text[:400]
            try:
                wait = float(r.headers.get("Retry-After") or (r.json() or {}).get("retryAfter") or 0)
            except (ValueError, TypeError):
                wait = 0.0
            # 하루 한도 소진처럼 곧 풀리지 않을 제한이면 이 회차에는 더 두드리지 않는다
            if wait > 300 or "budget" in body.lower() or "insufficient" in body.lower():
                reason = "오늘 무료 조회 한도 초과"
                if source:
                    _unavailable[source] = reason
                raise LookupFailed(f"{source or ''} {reason}".strip())
            await asyncio.sleep(min(wait or 1.0 * (attempt + 1), 5.0))
            continue
        if r.status_code in (500, 502, 503, 504):          # 일시적 실패는 잠시 쉬었다 다시
            await asyncio.sleep(1.0 * (attempt + 1))
            continue
        break
    raise LookupFailed(last or "알 수 없는 오류")


def _cr_item(it: dict) -> Candidate:
    title = (it.get("title") or [""])[0]
    alts = list(it.get("original-title") or []) + list(it.get("subtitle") or [])
    authors = []
    for a in it.get("author") or []:
        fam = a.get("family") or a.get("name") or ""
        if fam:
            authors.append((fam + " " + (a.get("given") or "")).strip())
    year = None
    for k in ("issued", "published-print", "published-online", "created"):
        dp = ((it.get(k) or {}).get("date-parts") or [[None]])[0]
        if dp and dp[0]:
            year = str(dp[0])
            break
    cont = (it.get("container-title") or [None])[0]
    doi = it.get("DOI")
    return Candidate("crossref", title, authors, year, cont, doi,
                     ("https://doi.org/" + doi) if doi else it.get("URL"),
                     {"type": it.get("type"), "volume": it.get("volume"), "issue": it.get("issue"),
                      "pages": it.get("page"), "publisher": it.get("publisher")},
                     alt_titles=alts)


async def crossref_by_doi(client, doi: str):
    url = f"{CROSSREF}/{quote(doi, safe='')}"
    data = await _get_json(client, url, _sem_crossref, "Crossref")
    if data.get("_404"):
        return "404"
    it = data.get("message") or {}
    return _cr_item(it) if it else None


_CR_SELECT = "DOI,title,author,issued,container-title,score,original-title,subtitle,type,URL,volume,issue,page,publisher"


async def crossref_search(client, q: str, rows: int = 5, by_title: bool = False) -> list[Candidate]:
    q = re.sub(r"\s+", " ", q).strip()[:600]
    if len(q) < 8:
        return []
    field = "query.title" if by_title else "query.bibliographic"
    url = f"{CROSSREF}?{field}={quote(q)}&rows={rows}&select={_CR_SELECT}"
    data = await _get_json(client, url, _sem_crossref, "Crossref")
    if data.get("_404"):
        return []
    return [_cr_item(it) for it in (data.get("message") or {}).get("items") or []]


def _oa_item(it: dict) -> Candidate:
    title = it.get("title") or it.get("display_name") or ""
    authors = [(a.get("author") or {}).get("display_name") for a in it.get("authorships") or []]
    authors = [a for a in authors if a]
    year = str(it["publication_year"]) if it.get("publication_year") else None
    loc = it.get("primary_location") or {}
    src = (loc.get("source") or {}).get("display_name")
    doi = it.get("doi")
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    oa = it.get("open_access") or {}
    bib = it.get("biblio") or {}
    pages = None
    if bib.get("first_page"):
        pages = bib["first_page"] + (("-" + bib["last_page"]) if bib.get("last_page") else "")
    extra = {"oa_pdf": oa.get("oa_url") or loc.get("pdf_url"), "openalex": it.get("id"), "type": it.get("type"),
             "volume": bib.get("volume"), "issue": bib.get("issue"), "pages": pages}
    landing = ("https://doi.org/" + doi) if doi else (loc.get("landing_page_url") or it.get("id"))
    return Candidate("openalex", title, authors, year, src, doi, landing, extra)


_OA_SELECT = "id,doi,title,display_name,publication_year,authorships,primary_location,open_access,type,biblio"


async def openalex_search(client, q: str, rows: int = 5, api_key: str = "") -> list[Candidate]:
    q = re.sub(r"[\"“”「」『』]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()[:300]
    if len(q) < 6:
        return []
    url = f"{OPENALEX}?search={quote(q)}&per-page={rows}&select={_OA_SELECT}"
    if api_key:
        url += "&api_key=" + quote(api_key)
    data = await _get_json(client, url, _sem_openalex, "OpenAlex")
    if data.get("_404"):
        return []
    return [_oa_item(it) for it in data.get("results") or []]


# ---------------------------------------------------------------- RISS
def _clean_query(s: str) -> str:
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[\(（]\s*(?:1[89]|20)\d{2}[a-z]?\s*[\)）]", " ", s)
    s = re.sub(r"[\"“”「」『』‘’'\.,:;\(\)\[\]/·\-–—]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _riss_queries(ref: ParsedRef) -> list[str]:
    """긴 제목은 RISS에서 오히려 안 걸리므로 짧은 변형도 같이 준비한다."""
    out: list[str] = []
    title = _clean_query(ref.title or "")
    if title:
        out.append(title[:120])
        words = title.split()
        if len(words) > 8:
            out.append(" ".join(words[:8]))
        # 부제 앞부분만
        head = re.split(r"\s[:：]\s|\s-\s", ref.title or "", maxsplit=1)[0]
        head = _clean_query(head)
        if head and head != title and len(head) >= 6:
            out.append(head[:120])
    if not out:
        out.append(_clean_query(ref.raw)[:120])
    seen, uniq = set(), []
    for q in out:
        if len(q) >= 4 and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:3]


def _korea_related(ref: ParsedRef) -> bool:
    return ref.lang == "ko" or bool(KOREA_HINT_RE.search(ref.raw))


def _riss_cols(ref: ParsedRef) -> list[str]:
    """자료유형에 맞는 컬렉션을 우선순위대로. 전수조사에서는 뒤 것까지 훑는다."""
    if ref.kind == "thesis":
        return ["bib_t", "re_a_kor"]
    if ref.kind == "book":
        return ["bib_m", "re_t"]
    if ref.kind == "report":
        return ["re_t", "re_a_kor", "bib_m"]
    if ref.lang != "ko":
        return ["re_a_kor", "re_a_over"] if _korea_related(ref) else ["re_a_over", "re_a_kor"]
    return ["re_a_kor", "bib_t", "re_t"]


async def riss_search_cached(client, q: str, col: str) -> list[riss.RissItem]:
    key = f"riss:{col}:{q}"
    hit = cache.get(key)
    if hit is not None:
        return [riss.RissItem(**d) for d in hit]
    last = ""
    for attempt in range(2):
        try:
            items = await riss.search(client, q, col)
        except httpx.HTTPError as e:
            last = type(e).__name__
            await asyncio.sleep(1.0 * (attempt + 1))
            continue
        cache.put(key, [i.to_dict() for i in items[:10]])
        return items[:10]
    raise LookupFailed("RISS " + last)


def _riss_cand(it: riss.RissItem) -> Candidate:
    return Candidate("riss", it.title, it.authors, it.year, it.container or it.publisher, it.doi, it.detail_url,
                     {"fulltext": it.fulltext, "kci": it.kci, "col": it.col,
                      "col_label": riss.COLS.get(it.col, ""), "publisher": it.publisher,
                      "volume": it.volume, "permalink": it.permalink, "detail_url": it.detail_url})


async def riss_lookup(client, ref: ParsedRef, exhaustive: bool) -> list[Candidate]:
    """확실한 일치가 나오면 멈추고, 없으면 컬렉션과 질의 변형을 넓혀 계속 찾는다."""
    queries = _riss_queries(ref)
    cols = _riss_cols(ref)
    if not exhaustive:
        queries, cols = queries[:1], cols[:1]
    found: dict[str, Candidate] = {}
    failures = 0
    for qi, q in enumerate(queries):
        for col in cols:
            try:
                items = await riss_search_cached(client, q, col)
            except LookupFailed:
                failures += 1
                continue
            for it in items:
                key = it.control_no or norm_for_match(it.title)[:60]
                if key in found:
                    continue
                c = _riss_cand(it)
                score_candidate(ref, c)
                found[key] = c
            if any(_is_strong(c) for c in found.values()):
                return list(found.values())
        if qi == 0 and found and max(c.title_sim for c in found.values()) >= 80:
            # 첫 질의에서 그럴듯한 것이 나왔으면 변형까지는 가지 않는다
            break
    if not found and failures:
        raise LookupFailed(f"RISS 조회 {failures}건 실패")
    return list(found.values())


async def check_url(client, url: str) -> tuple[str, str]:
    async with _sem_web:
        try:
            r = await client.head(url, timeout=12.0, follow_redirects=True, headers={"User-Agent": riss.UA})
            if r.status_code in (405, 403, 400):
                r = await client.get(url, timeout=12.0, follow_redirects=True, headers={"User-Agent": riss.UA})
        except httpx.HTTPError as e:
            return "unverified", f"URL 접속 실패({type(e).__name__}). 주소가 폐기되었거나 서버가 응답하지 않습니다."
    if r.status_code < 400:
        return "verified", f"URL 접속 확인(HTTP {r.status_code})"
    if r.status_code in (401, 403, 429):
        return "likely", f"서버가 자동 접속을 차단(HTTP {r.status_code})했습니다. 브라우저에서 직접 확인하세요."
    return "unverified", f"URL 응답 오류(HTTP {r.status_code})"


# ---------------------------------------------------------------- 링크
def _law_name(raw: str) -> Optional[str]:
    m = re.search(r"([가-힣·\s]{2,40}?(?:법률|법|시행령|시행규칙|규칙|고시|조례))", raw)
    return m.group(1).strip() if m else None


def build_links(ref: ParsedRef, best: Optional[Candidate], status: str) -> list[dict]:
    links: list[dict] = []
    q = ref.title or ref.raw[:200]
    if best is not None and status in ("verified", "likely"):
        if best.doi:
            links.append({"label": "DOI 원문", "url": "https://doi.org/" + best.doi, "kind": "primary"})
        if best.source == "riss":
            tag = {"free": " (무료)", "paid": " (유료)", "yes": ""}.get(best.extra.get("fulltext"), "")
            links.append({"label": "RISS 상세·원문보기" + tag,
                          "url": best.extra.get("permalink") or best.extra.get("detail_url") or best.url,
                          "kind": "primary"})
        elif best.extra.get("riss_permalink"):
            tag = {"free": " (무료)", "paid": " (유료)", "yes": ""}.get(best.extra.get("riss_fulltext"), "")
            links.append({"label": "RISS 상세·원문보기" + tag, "url": best.extra["riss_permalink"], "kind": "primary"})
        if best.extra.get("oa_pdf"):
            links.append({"label": "무료 PDF", "url": best.extra["oa_pdf"], "kind": "primary"})
        if best.source == "openalex" and best.extra.get("openalex") and not best.doi:
            links.append({"label": "OpenAlex", "url": best.extra["openalex"], "kind": "secondary"})
        if best.source != "riss" and not best.extra.get("riss_permalink"):
            col = "re_a_over" if (ref.lang != "ko" and not _korea_related(ref)) else "re_a_kor"
            links.append({"label": "RISS에서 검색", "url": riss.search_url(q, col), "kind": "secondary"})
    else:
        if ref.kind == "law":
            name = _law_name(ref.raw) or q
            links.append({"label": "국가법령정보센터", "url": "https://www.law.go.kr/법령/" + quote(name), "kind": "primary"})
            links.append({"label": "법령 검색",
                          "url": "https://www.law.go.kr/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81&query=" + quote(name),
                          "kind": "secondary"})
        else:
            col = {"thesis": "bib_t", "book": "bib_m", "report": "re_t"}.get(
                ref.kind, "re_a_kor" if _korea_related(ref) else "re_a_over")
            links.append({"label": "RISS에서 검색", "url": riss.search_url(q, col), "kind": "primary"})
        if ref.doi:
            links.append({"label": "DOI 링크(확인 필요)", "url": "https://doi.org/" + ref.doi, "kind": "secondary"})
    if ref.url and ref.kind == "web":
        links.insert(0, {"label": "원문 URL", "url": ref.url, "kind": "primary"})
    # 회색문헌(보고서·단행본)은 일반 웹검색이 가장 잘 듣는다
    if ref.kind in ("report", "book", "unknown") and status != "verified":
        links.append({"label": "ScienceON 검색",
                      "url": "https://scienceon.kisti.re.kr/srch/selectPORSrchArticle.do?searchQuery=" + quote(q),
                      "kind": "secondary"})
        links.append({"label": "구글 웹검색", "url": "https://www.google.com/search?q=" + quote(q), "kind": "secondary"})
    if _korea_related(ref) and ref.kind != "law":
        links.append({"label": "DBpia 검색",
                      "url": "https://www.dbpia.co.kr/search/topSearch?searchOption=all&query=" + quote(q),
                      "kind": "secondary"})
    links.append({"label": "Google Scholar", "url": "https://scholar.google.com/scholar?q=" + quote(q), "kind": "secondary"})
    seen, out = set(), []
    for l in links:
        if l["url"] and l["url"] not in seen:
            seen.add(l["url"])
            out.append(l)
    return out


# ---------------------------------------------------------------- 한 항목 검사
def _merge(pool: dict[str, Candidate], cands: list[Candidate]) -> None:
    for c in cands:
        key = (c.doi or "").lower() or norm_for_match(c.title)[:60]
        if not key:
            continue
        cur = pool.get(key)
        if cur is None:
            pool[key] = c
        elif c.source == "riss" and cur.source != "riss":
            cur.extra.setdefault("riss_permalink", c.extra.get("permalink") or c.extra.get("detail_url"))
            cur.extra.setdefault("riss_fulltext", c.extra.get("fulltext"))
            if c.extra.get("kci"):
                cur.extra.setdefault("kci", c.extra["kci"])
        elif c.score > cur.score:
            pool[key] = c


async def check_one(client: httpx.AsyncClient, ref: ParsedRef, opts: Options) -> RefResult:
    t0 = time.time()
    notes: list[str] = []
    flags: list[str] = []
    sources: list[str] = []

    if ref.kind == "law":
        return RefResult(ref.to_dict(), "skipped", STATUS_LABEL["skipped"], KIND_LABEL["law"], None, [],
                         build_links(ref, None, "skipped"),
                         "법령·고시는 서지 DB 대상이 아니어서 자동 확인하지 않습니다. 국가법령정보센터에서 조문과 시행일을 직접 확인하세요.",
                         round(time.time() - t0, 2), ["직접 확인 필요"], [])

    if ref.kind == "web" and ref.url and not ref.doi:
        if not opts.check_urls:
            status, msg = "skipped", "URL 접속 확인을 건너뛰었습니다."
        else:
            status, msg = await check_url(client, ref.url)
        fl = [] if status == "verified" else ["링크 확인 필요"]
        return RefResult(ref.to_dict(), status, STATUS_LABEL[status], KIND_LABEL["web"], None, [],
                         build_links(ref, None, status), msg, round(time.time() - t0, 2), fl, ["웹"])

    pool: dict[str, Candidate] = {}
    doi_state: Optional[str] = None
    doi_cand: Optional[Candidate] = None

    # 1단계: DOI 직접 조회 + Crossref (+ 국내 문헌이면 RISS)
    # OpenAlex 는 하루 무료 한도가 100회뿐이라, 앞의 두 곳에서 확실히 찾지 못한 건에만 뒤에서 부른다.
    tasks: dict[str, object] = {}
    if ref.doi:
        tasks["doi"] = crossref_by_doi(client, ref.doi)
    tasks["crossref"] = crossref_search(client, ref.raw)
    want_riss = _korea_related(ref) or opts.riss_all
    if want_riss:
        tasks["riss"] = riss_lookup(client, ref, opts.exhaustive)

    SRC_LABEL = {"doi": "DOI", "crossref": "Crossref", "crossref_title": "Crossref",
                 "openalex": "OpenAlex", "riss": "RISS"}
    keys = list(tasks)
    got = await asyncio.gather(*tasks.values(), return_exceptions=True)
    errors: list[str] = []
    for k, res in zip(keys, got):
        if isinstance(res, BaseException):
            errors.append(SRC_LABEL.get(k, k))
            continue
        if k == "doi":
            if res == "404":
                doi_state = "404"
            elif isinstance(res, Candidate):
                res.source = "doi"
                score_candidate(ref, res)
                doi_cand = res
            sources.append("DOI")
        else:
            sources.append(SRC_LABEL.get(k, k))
            if res:
                for c in res:
                    if c.source != "riss":
                        score_candidate(ref, c)
                _merge(pool, list(res))

    def best_now() -> Optional[Candidate]:
        return max(pool.values(), key=lambda c: c.score) if pool else None

    # 2단계: 확실한 일치가 없을 때만 Crossref 를 제목으로 한 번 더 (호출량을 아낀다)
    b = best_now()
    if opts.exhaustive and ref.title and (b is None or not _is_strong(b)):
        try:
            extra = await crossref_search(client, ref.title, by_title=True)
            for c in extra:
                score_candidate(ref, c)
            _merge(pool, extra)
        except (httpx.HTTPError, LookupFailed):
            errors.append("Crossref")
        b = best_now()

    # 3단계: 그래도 없으면 RISS까지 넓혀 다시 훑는다(전수조사)
    if opts.exhaustive and not want_riss and (b is None or not _is_strong(b)):
        try:
            _merge(pool, await riss_lookup(client, ref, True))
            sources.append("RISS")
        except (httpx.HTTPError, LookupFailed):
            errors.append("RISS")
        b = best_now()

    # 4단계: 그래도 확실하지 않으면 이제 OpenAlex 를 부른다 (제목으로, 그래도 없으면 원문으로)
    if b is None or not _is_strong(b):
        for q in filter(None, [ref.title or ref.raw, ref.raw[:300] if opts.exhaustive and ref.title else None]):
            try:
                extra = await openalex_search(client, q, api_key=opts.openalex_key)
                for c in extra:
                    score_candidate(ref, c)
                _merge(pool, extra)
                if "OpenAlex" not in sources:
                    sources.append("OpenAlex")
            except (httpx.HTTPError, LookupFailed):
                errors.append("OpenAlex")
                break
            b = best_now()
            if b is not None and _is_strong(b):
                break

    doi_confirmed = False
    if doi_cand is not None:
        if doi_cand.title_sim >= 85:
            doi_confirmed = True
            doi_cand.score = max(doi_cand.score, 0.95)
            _merge(pool, [doi_cand])
            notes.append("DOI로 서지 확인")
        else:
            flags.append("DOI 제목 불일치")
            notes.append(f"기재된 DOI는 존재하지만 제목이 다릅니다(DOI 등록 제목: {doi_cand.title[:60]})")
    if doi_state == "404":
        flags.append("DOI 없음")
        notes.append("기재된 DOI를 Crossref에서 찾을 수 없습니다")

    ranked = sorted(pool.values(), key=lambda c: -c.score)
    best = ranked[0] if ranked else None
    status, dec_flags, show_best = decide(best, opts.strict, doi_confirmed)
    # 근거가 약한 후보를 '확인된 서지'로 보여 주면 심사자를 오도한다
    if not show_best:
        best = None
    flags.extend(dec_flags)

    # RISS 링크 보강
    if best is not None and status in ("verified", "likely"):
        if best.source == "riss" and best.extra.get("detail_url") and not best.extra.get("permalink"):
            try:
                d = await riss.detail(client, best.extra["detail_url"])
                if d.get("permalink"):
                    best.extra["permalink"] = d["permalink"]
                if d.get("doi") and not best.doi:
                    best.doi = d["doi"]
            except httpx.HTTPError:
                pass
        elif best.source != "riss" and not best.extra.get("riss_permalink"):
            for c in ranked:
                if c.source == "riss" and c.title_sim >= 85 and c.score >= 0.6:
                    best.extra["riss_permalink"] = c.extra.get("permalink") or c.extra.get("detail_url")
                    best.extra["riss_fulltext"] = c.extra.get("fulltext")
                    break

    if best is not None:
        src_label = {"crossref": "Crossref", "openalex": "OpenAlex", "riss": "RISS", "doi": "DOI"}[best.source]
        notes.append(f"{src_label}에서 후보 발견(제목 유사도 {best.title_sim:.0f}%)")
        if best.year_ok is False:
            notes.append(f"연도 불일치(문헌 {ref.year} / 후보 {best.year})")
        if best.author_ok is False:
            notes.append(f"첫 저자 불일치(문헌 {ref.first_author} / 후보 {', '.join(best.authors[:2])})")
        if best.container_ok is False:
            notes.append(f"게재지 불일치(문헌 {ref.container} / 후보 {best.container})")
        if best.extra.get("kci"):
            notes.append(best.extra["kci"])
    else:
        notes.append("일치하는 항목을 찾지 못했습니다")
        if ref.kind in ("book", "report", "unknown", "thesis"):
            notes.append("단행본·기관보고서·학위논문은 서지 DB 수록률이 낮아 미확인이 곧 허위를 뜻하지는 않습니다. 아래 검색 링크로 확인하세요")

    if status == "unverified":
        flags.append("직접 확인 필요")
    # 같은 조회처의 여러 질의 중 하나만 실패한 경우는 실패로 세지 않는다
    errors = [s for s in errors if s not in sources]
    if errors:
        blocked = [s for s in dict.fromkeys(errors) if s in _unavailable]
        transient = [s for s in dict.fromkeys(errors) if s not in _unavailable]
        if blocked:
            # 하루 한도 초과처럼 예측 가능한 제한은 항목마다 겁주지 않고 위쪽에서 한 번만 알린다
            notes.append(", ".join(blocked) + "은(는) 이번 조회에서 사용하지 못했습니다")
            if status != "verified":
                flags.append("조회처 일부 사용 불가")
        if transient:
            notes.append(", ".join(transient) + " 조회에 실패했습니다. 찾지 못한 것이 아니라 접속이 안 된 것이므로 다시 실행해 보세요")
            flags.append("조회 실패")
            if status == "unverified" and "직접 확인 필요" in flags:
                flags.remove("직접 확인 필요")
                flags.append("재실행 필요")

    links = build_links(ref, best, status)
    return RefResult(ref.to_dict(), status, STATUS_LABEL[status], KIND_LABEL.get(ref.kind, ref.kind),
                     best.to_dict() if best else None,
                     [c.to_dict() for c in ranked[:5]], links, " · ".join(notes),
                     round(time.time() - t0, 2), list(dict.fromkeys(flags)), list(dict.fromkeys(sources)))


# ---------------------------------------------------------------- 전체 실행
def _mark_duplicates(results: list[RefResult]) -> None:
    groups: dict[str, list[RefResult]] = {}
    for r in results:
        t = norm_for_match(r.ref.get("title") or "")
        key = (t[:70] or norm_for_match(r.ref.get("raw") or "")[:70]) + "|" + (r.ref.get("year") or "")
        if len(key) > 5:
            groups.setdefault(key, []).append(r)
    for items in groups.values():
        if len(items) > 1:
            nums = ", ".join(str(i.ref["index"]) for i in items)
            for r in items:
                r.flags.append("중복 기재")
                r.note = (r.note + " · " if r.note else "") + f"같은 문헌이 여러 번 올라와 있습니다(항목 {nums})"


async def verify_all(raw_refs: list[str], opts: Options,
                     on_result: Optional[Callable[[int, RefResult], None]] = None,
                     concurrency: int = 6) -> list[RefResult]:
    reset_sources()
    refs = [parse_reference(i + 1, r) for i, r in enumerate(raw_refs)]
    results: list[Optional[RefResult]] = [None] * len(refs)
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
    async with httpx.AsyncClient(limits=limits, http2=False) as client:
        async def run(i: int, ref: ParsedRef):
            async with sem:
                try:
                    res = await check_one(client, ref, opts)
                except Exception as e:      # noqa: BLE001 - 한 항목 실패가 전체를 막지 않게
                    res = RefResult(ref.to_dict(), "error", STATUS_LABEL["error"],
                                    KIND_LABEL.get(ref.kind, ref.kind), None, [],
                                    build_links(ref, None, "error"),
                                    f"처리 중 오류: {type(e).__name__}: {e}", 0.0, ["직접 확인 필요"], [])
                results[i] = res
                if on_result:
                    on_result(i, res)
        await asyncio.gather(*(run(i, r) for i, r in enumerate(refs)))
    out = [r for r in results if r is not None]
    _mark_duplicates(out)
    return out
