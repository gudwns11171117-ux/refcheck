# -*- coding: utf-8 -*-
"""참고문헌 한 항목 문자열에서 DOI·URL·연도·제목·저자·언어·자료유형을 뽑아낸다."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Optional

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>,;]+)", re.I)
URL_RE = re.compile(r"(https?://[^\s<>\"'）\)]+|www\.[^\s<>\"'）\)]+)", re.I)
YEAR_PAREN_RE = re.compile(r"[\(（]\s*((?:1[89]\d{2}|20\d{2}))\s*[a-z]?\s*(?:[,\.]\s*[A-Za-z가-힣]+\s*\d{0,2})?\s*[\)）]")
YEAR_ANY_RE = re.compile(r"(?<![\d\-/\.])((?:1[89]\d{2}|20\d{2}))(?![\d\-/])")
HANGUL_RE = re.compile(r"[가-힣]")
LATIN_RE = re.compile(r"[A-Za-z]")
QUOTED_RE = re.compile(r"[\"“”](.+?)[\"“”]|「(.+?)」|‘(.+?)’|'(.{12,}?)'")
VOL_RE = re.compile(
    r"\b\d{1,3}\s*[\(（]\s*\d{1,3}\s*[\)）]|Vol\.?\s*\d|\bno\.?\s*\d|제\s*\d+\s*[권호집]|\d+\s*권|\d+\s*호|pp?\.\s*\d|\d+\s*[-–~]\s*\d+\s*(?:쪽|면|p)?\s*\.?$",
    re.I,
)
THESIS_RE = re.compile(r"학위\s*논문|석사|박사|dissertation|thesis|Ph\.?\s?D|Master['’]?s|Doctoral|대학원", re.I)
LAW_RE = re.compile(
    r"(?:법률|시행령|시행규칙|고시|훈령|예규|조례|규칙)\b|법\s*제\s*\d+\s*조|제\s*\d+\s*조|국가법령정보센터|법제처|"
    r"(?:산업안전보건법|근로기준법|중대재해\s*처벌\s*등에\s*관한\s*법률|중대재해처벌법)|\bAct\b(?!\w)|\bRegulation\b|\bDirective\b|"
    # 영문으로 인용된 정부 고시·지침 (예: Ministry of Employment and Labor (2020). Guidelines ... [2020-53])
    r"Ministry\s+of\s+[A-Za-z\s]{3,40}\s*\(\s*(?:19|20)\d{2}\s*\)[^.]{0,120}?\b(?:Guidelines?|Notice|Public\s+Notice)\b|"
    r"\bGuidelines?\b[^.]{0,80}?\[\s*(?:19|20)\d{2}\s*[-–]\s*\d{1,4}\s*\]",
    re.I,
)
REPORT_RE = re.compile(
    r"보고서|연구\s*보고|정책\s*보고|백서|지침|가이드\s*라인|가이드|매뉴얼|Report|White\s*Paper|Guideline|Technical\s+Note|"
    r"Working\s+Paper|고용노동부|안전보건공단|KOSHA|OSHA|NIOSH|HSE|ILO|OECD|WHO|Ministry|통계청|연구원|진흥원",
    re.I,
)
BOOK_RE = re.compile(
    r"(?:Press|Publish(?:ing|ers|er)|Wiley|Springer|Elsevier|Routledge|Sage|McGraw-Hill|Pearson|Prentice\s*Hall)\b|"
    r"출판사|출판부|출판|(?:서울|부산|파주|경기)\s*[:：]|\d+(?:st|nd|rd|th)\s+ed\.?|\bed\.\)|\bEds?\.|제\s*\d+\s*판|개정판|증보판|(?:^|\s)In\s+[A-Z]|"
    r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s*:\s*[A-Z][A-Za-z&\.\s\-]+\.?\s*$",      # 끝부분의 "New York: McGraw-Hill."
    re.I,
)
WEB_RE = re.compile(r"Retrieved|Accessed|Available\s+(?:at|from)|접속|검색일|열람|조회|다운로드|홈페이지|웹사이트|website", re.I)
# 기관 발간물 표시: 발행기관 이름과 보고서 번호(2014-Researcher-959, 연구원 2014-959 등)
ORG_EN_RE = re.compile(
    r"\b(?:Agency|Institute|Administration|Corporation|Ministry|Bureau|Commission|Council|Authority|"
    r"Foundation|Association|Organization|Organisation|Department\s+of|Office\s+of)\b",
    re.I,
)
REPORT_NO_RE = re.compile(
    r"\b(?:19|20)\d{2}\s*[-–]\s*[A-Za-z가-힣]{2,20}\s*[-–]\s*\d{1,5}\b|"
    r"보고서\s*번호|연구\s*보고서?\s*(?:제\s*)?\d|(?:연구원|공단|연구소)\s*(?:19|20)\d{2}\s*[-–]\s*\d+",
    re.I,
)
KOREA_HINT_RE = re.compile(
    r"\bKorea[n]?\b|\bSeoul\b|\bKOSHA\b|\bKCI\b|\bIncheon\b|\bBusan\b|\bDaejeon\b|\bUlsan\b|"
    r"\bRepublic\s+of\s+Korea\b|한국|대한|국내",
    re.I,
)
ET_AL_RE = re.compile(r"\bet\s+al\.?|외\s*\d*\s*(?:인|명)?|등\b")


@dataclass
class ParsedRef:
    index: int
    raw: str
    doi: Optional[str] = None
    url: Optional[str] = None
    year: Optional[str] = None
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    first_author: Optional[str] = None
    container: Optional[str] = None
    lang: str = "en"          # ko | en | other
    kind: str = "unknown"     # article | thesis | book | report | law | web | unknown

    def to_dict(self):
        return asdict(self)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_title(t: str) -> str:
    t = t.strip()
    t = re.sub(r"^[\s\"“”「」『』‘’'\.,:;]+", "", t)
    t = re.sub(r"[\s\"“”「」『』‘’',:;]+$", "", t)
    t = re.sub(r"\.$", "", t).strip()
    return t


def detect_lang(s: str) -> str:
    h = len(HANGUL_RE.findall(s))
    l = len(LATIN_RE.findall(s))
    if h == 0 and l == 0:
        return "other"
    return "ko" if h / max(1, h + l) >= 0.25 else "en"


def _mask(s: str) -> str:
    """DOI/URL 부분을 공백으로 가려서 연도·제목 추출에 끼어들지 않게 한다."""
    s = URL_RE.sub(lambda m: " " * len(m.group(0)), s)
    s = DOI_RE.sub(lambda m: " " * len(m.group(0)), s)
    return s


def _extract_year(masked: str) -> Optional[str]:
    m = YEAR_PAREN_RE.search(masked)
    if m:
        return m.group(1)
    ys = YEAR_ANY_RE.findall(masked)
    if not ys:
        return None
    # IEEE식 "..., 2020." 처럼 맨 끝에 연도가 오면 그것, 아니면 첫 연도
    if len(ys) > 1 and re.search(r",\s*" + ys[-1] + r"\s*\.?\s*$", masked.strip()):
        return ys[-1]
    return ys[0]


# 기관명(Occupational Safety and Health Administration). "M. D. Cooper" 같은 이니셜 나열은 제외한다.
ORG_RE = re.compile(r"^(?:(?:[A-Z][A-Za-z&\-]{2,}|and|of|for|the|on|in)\s+){2,}[A-Z][A-Za-z\-]{2,}\.?$")


def _split_authors(chunk: str, lang: str) -> list[str]:
    chunk = ET_AL_RE.sub(" ", chunk)
    chunk = re.sub(r"[\(（].*?[\)）]", " ", chunk)          # (Kim, J. H.) 같은 괄호 병기 제거
    bare = chunk.strip(" .,;:")
    if lang != "ko" and "," not in bare and ORG_RE.match(bare):   # 기관명(Occupational Safety and Health Administration)
        return [bare]
    chunk = (chunk.replace("&", ",").replace(" and ", ",").replace("·", ",").replace("・", ",")
             .replace("、", ",").replace(";", ","))
    parts = [p.strip(" .") for p in chunk.split(",")]
    names: list[str] = []
    if lang == "ko":
        for p in parts:
            p = p.strip()
            m = re.match(r"^[가-힣]{2,5}", p)
            if m and not re.match(r"^(?:제목|저자|편|역|공저|편저|옮김|지음)$", m.group(0)):
                names.append(m.group(0))
    else:
        i = 0
        while i < len(parts):
            p = parts[i]
            if not p:
                i += 1
                continue
            # "Kim, J. H." → 성 + 이니셜 재조합
            if (re.fullmatch(r"[A-Z][A-Za-z'’\-]+(?:\s[A-Z][A-Za-z'’\-]+)?", p) and i + 1 < len(parts)
                    and re.fullmatch(r"(?:[A-Z]\.?\s*){1,3}[A-Za-z\-]*", parts[i + 1])):
                names.append(p)
                i += 2
                continue
            m = re.match(r"^(?:[A-Z]\.\s*){1,3}([A-Z][A-Za-z'’\-]+)$", p)      # J. H. Kim
            if m:
                names.append(m.group(1))
            elif re.fullmatch(r"[A-Z][A-Za-z'’\-]+\s+[A-Z][A-Za-z'’\-]+", p):    # John Kim
                names.append(p.split()[-1])
            elif re.fullmatch(r"[A-Z][A-Za-z'’\-]{2,}", p):
                names.append(p)
            elif re.fullmatch(r"[A-Z]{2,}[A-Za-z\s&]*", p):                   # 기관명 약자
                names.append(p.strip())
            i += 1
    return names[:12]


def _extract_title(masked: str, year: Optional[str], lang: str) -> tuple[Optional[str], str]:
    """(제목, 저자부) 반환. 저자부는 제목 앞부분 원문."""
    # 1) 따옴표/낫표
    best = None
    for m in QUOTED_RE.finditer(masked):
        q = next(g for g in m.groups() if g)
        if len(q) >= 8 and (best is None or len(q) > len(best[0])):
            best = (q, m.start())
    if best:
        return _clean_title(best[0]), masked[:best[1]]
    # 2) APA: 저자(연도). 제목. 저널...
    if year:
        m = re.search(r"[\(（]\s*" + re.escape(year) + r"[a-z]?\s*(?:[,\.]\s*[A-Za-z가-힣]+\s*\d{0,2})?\s*[\)）]\s*[\.:,]?\s*", masked)
        if m and m.end() < len(masked) - 5:
            rest = masked[m.end():]
            parts = re.split(
                r"(?<=[^\s\.A-Z])\.\s+(?=[A-Z가-힣『\"“])|(?<=[가-힣\)])\.\s*(?=[A-Z가-힣『])|\.\s+(?=In\s)|\?\s+(?=[A-Z가-힣])",
                rest, maxsplit=1)
            title = parts[0]
            if len(title) > 250:
                title = re.split(r"\.\s", title, maxsplit=1)[0]
            if len(title) >= 6:
                return _clean_title(title), masked[:m.start()]
        # 2b) 저자, 연도, 제목 (연도가 괄호 없이 앞쪽에)
        m = re.search(r"(?<![\d\-])" + re.escape(year) + r"[a-z]?\s*[\.,:]\s+", masked)
        if m and m.start() < len(masked) * 0.5:
            rest = masked[m.end():]
            title = re.split(r"(?<=[^\s\.A-Z])\.\s+(?=[A-Z가-힣『\"“])|,\s+(?=[A-Z가-힣]{2,}[^,]*,\s*\d)|\.\s*$", rest, maxsplit=1)[0]
            if len(title) >= 6:
                return _clean_title(title), masked[:m.start()]
    # 2c) "저자, 제목. 발행지: 출판사, 연도." 형태 (IEEE 단행본 등, 괄호 연도가 없는 경우)
    #     제목 뒤에 문장 끝 마침표가 실제로 있을 때만 적용한다(쉼표로만 이어진 국문 인용을 통째로 삼키지 않게).
    m = re.match(
        r"^\s*(?:(?:[A-Z]\.\s*){1,3}[A-Z][A-Za-z'’\-]+"          # H. W. Heinrich
        r"|[A-Z][A-Za-z'’\-]+,\s*(?:[A-Z]\.\s*){1,3}"            # Heinrich, H. W.
        r"|[A-Z][A-Za-z'’\-]+"                                    # Heinrich
        r"|[가-힣]{2,5})\s*,\s+(?=[A-Z가-힣「『\"“])",
        masked,
    )
    if m:
        rest = masked[m.end():]
        cut = re.split(r"(?<=[^\s\.A-Z])\.\s+|\.\s*$", rest, maxsplit=1)[0]
        if 8 <= len(cut) < len(rest) - 2 and not VOL_RE.search(cut):
            return _clean_title(cut), masked[:m.end()]
    # 3) 마침표로 나눈 조각 중 가장 그럴싸한 것 (숫자 비중 낮고 길이 충분)
    segs = [s.strip() for s in re.split(r"(?<=[^\s\.A-Z])\.\s+|\.\s*$", masked) if s.strip()]
    if len(segs) >= 2:
        cands = []
        for i, s in enumerate(segs[1:], 1):
            digits = len(re.findall(r"\d", s))
            if len(s) >= 10 and digits / max(1, len(s)) < 0.15 and not VOL_RE.search(s):
                cands.append((len(s), i, s))
        if cands:
            cands.sort(reverse=True)
            _, i, s = cands[0]
            return _clean_title(s), ". ".join(segs[:i])
    return None, masked[: min(len(masked), 80)]


def _extract_container(masked: str, title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    key = title[:30] if len(title) >= 30 else title
    i = masked.find(key)
    if i < 0:
        return None
    rest = masked[i + len(title):]
    rest = re.sub(r"^[\s\.,\"”」’:;]+", "", rest)
    m = re.match(r"(?:In\s+)?([^,\.\d\(（『]{3,80}?)(?:[,\.]|\s+\d|\s*[\(（]|\s*『|$)", rest)
    if m:
        c = m.group(1).strip(" ,.『』")
        if 2 < len(c) <= 80 and not YEAR_ANY_RE.search(c):
            return c
    return None


def classify(masked: str, doi: Optional[str], url: Optional[str]) -> str:
    if re.search(r"학위\s*논문|dissertation|thesis", masked, re.I):
        return "thesis"
    if THESIS_RE.search(masked) and not VOL_RE.search(masked):
        return "thesis"
    if LAW_RE.search(masked) and not VOL_RE.search(masked) and not doi:
        return "law"
    if url and not doi and (WEB_RE.search(masked) or not YEAR_ANY_RE.search(masked) or not VOL_RE.search(masked)):
        return "web"
    # 기관 발간 보고서: 권·호가 없고 발행기관 이름이나 보고서 번호가 붙는다.
    # (예: "Korea Occupational Safety and Health Agency, 2014-Researcher-959")
    if not doi and not VOL_RE.search(masked):
        if REPORT_NO_RE.search(masked) or REPORT_RE.search(masked) or ORG_EN_RE.search(masked):
            return "report"
    if doi or VOL_RE.search(masked):
        return "article"
    if BOOK_RE.search(masked):
        return "book"
    if REPORT_RE.search(masked):
        return "report"
    return "unknown"


def parse_reference(index: int, raw: str) -> ParsedRef:
    raw = _norm(raw)
    # 앞머리 번호([3] / (3) / 3. / 3)) 제거
    raw = re.sub(r"^\s*(?:\[\s*\d{1,3}\s*\]|\(\s*\d{1,3}\s*\)|\d{1,3}\s*[\.\)])\s+(?=\S)", "", raw)
    r = ParsedRef(index=index, raw=raw)
    m = DOI_RE.search(raw)
    if m:
        doi = m.group(1).rstrip(".,;)]}>\"'")
        r.doi = re.sub(r"[\.,;]+$", "", doi)
    m = URL_RE.search(raw)
    if m:
        u = m.group(0).rstrip(".,;)]}>\"'")
        if u.lower().startswith("www."):
            u = "http://" + u
        if "doi.org/" in u.lower() and not r.doi:
            mm = DOI_RE.search(u)
            if mm:
                r.doi = mm.group(1).rstrip(".,;)]}>\"'")
        r.url = u
    masked = _mask(raw)
    r.lang = detect_lang(masked)
    r.year = _extract_year(masked)
    r.title, author_part = _extract_title(masked, r.year, r.lang)
    r.authors = _split_authors(author_part, r.lang)
    r.first_author = r.authors[0] if r.authors else None
    r.container = _extract_container(masked, r.title)
    r.kind = classify(masked, r.doi, r.url)
    if r.kind == "law":
        r.authors, r.first_author = [], None
    return r


def norm_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[^0-9a-z가-힣\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
