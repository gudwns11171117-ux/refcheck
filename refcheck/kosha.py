# -*- coding: utf-8 -*-
"""안전보건공단(KOSHA) 산업안전보건연구원 연구보고서를 조회한다.

이 보고서들은 Crossref·RISS·OpenAlex 어디에도 색인되어 있지 않다. 안전보건 분야 논문에서
자주 인용되므로 공단 포털을 직접 조회해야 '확인 불가'로 잘못 넘기지 않는다.

공단 포털은 제목·저자를 국문으로만 담고 있고, 보고서 번호나 영문 제목으로는 검색되지 않는다.
그래서 영문으로 인용된 보고서는 (1) 발행연도로 그 해 목록을 받아 (2) 로마자 성을 한글 성으로 바꿔 거르고
(3) 영문 제목의 분야 용어를 국문 용어로 바꿔 제목과 맞춰 본다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

API = "https://portal.kosha.or.kr/api/portal24/bizV/p/VCPDG04001/searchRschList"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "chnlId": "portal24",          # 이 헤더가 없으면 400 이 돌아온다
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
}
DETAIL = "https://oshri.kosha.or.kr/oshri/publication/researchReportSearch.do?mode=view&articleNo={no}"
LIST_URL = "https://portal.kosha.or.kr/archive/research/Research-Data-Report1/Research-Data"

# 인용에 "KOSHA / 안전보건공단 / 산업안전보건연구원" 이 발행처로 적혀 있는지
PUBLISHER_RE = re.compile(
    r"KOSHA|Korea\s+Occupational\s+Safety\s+(?:and|&)\s+Health\s+(?:Agency|Corporation)|"
    r"Occupational\s+Safety\s+and\s+Health\s+Research\s+Institute|OSHRI|"
    r"안전보건공단|산업안전보건공단|산업안전보건연구원",
    re.I,
)
# 보고서 번호: 2015-Researcher-608 / 2015-연구원-608
REPORT_NO_RE = re.compile(r"(?:19|20)\d{2}\s*[-–]\s*(?:Researcher|연구원|OSHRI)\s*[-–]\s*(\d{1,5})", re.I)

# 로마자 성 -> 한글 성. 국내 연구보고서 저자를 거르는 데만 쓰므로 흔한 성만 담는다.
SURNAME: dict[str, tuple[str, ...]] = {
    "kim": ("김",), "lee": ("이", "리"), "yi": ("이",), "rhee": ("이",), "ri": ("이",),
    "park": ("박",), "pak": ("박",), "bak": ("박",),
    "choi": ("최",), "choe": ("최",),
    "jung": ("정",), "jeong": ("정",), "chung": ("정",), "cheong": ("정",),
    "kang": ("강",), "gang": ("강",),
    "cho": ("조",), "jo": ("조",), "joh": ("조",),
    "yoon": ("윤",), "yun": ("윤",),
    "jang": ("장",), "chang": ("장",),
    "lim": ("임",), "im": ("임",), "rim": ("임",),
    "han": ("한",), "oh": ("오",), "o": ("오",),
    "seo": ("서",), "suh": ("서",), "shin": ("신",), "sin": ("신",),
    "kwon": ("권",), "gwon": ("권",), "hwang": ("황",),
    "ahn": ("안",), "an": ("안",), "song": ("송",),
    "yoo": ("유", "류"), "yu": ("유", "류"), "ryu": ("류", "유"),
    "hong": ("홍",), "jeon": ("전",), "jun": ("전",), "chun": ("전", "천"),
    "ko": ("고",), "go": ("고",), "koh": ("고",),
    "moon": ("문",), "mun": ("문",), "son": ("손",), "sohn": ("손",),
    "yang": ("양",), "bae": ("배",), "pae": ("배",),
    "baek": ("백",), "paek": ("백",), "back": ("백",),
    "nam": ("남",), "noh": ("노",), "roh": ("노",), "no": ("노",),
    "ha": ("하",), "heo": ("허",), "huh": ("허",), "hur": ("허",),
    "sim": ("심",), "shim": ("심",), "min": ("민",), "chae": ("채",),
    "won": ("원",), "ji": ("지",), "cha": ("차",), "joo": ("주",), "ju": ("주",),
    "woo": ("우",), "koo": ("구",), "gu": ("구",), "ku": ("구",),
    "na": ("나",), "ra": ("나", "라"), "do": ("도",), "bang": ("방",), "pang": ("방",),
    "ma": ("마",), "wi": ("위",), "pyo": ("표",), "seok": ("석",), "sun": ("선",),
    "eom": ("엄",), "um": ("엄",), "gwak": ("곽",), "kwak": ("곽",),
    "byun": ("변",), "byeon": ("변",), "yeo": ("여",), "youn": ("윤",),
}

# 산업안전보건 분야 용어 대응표. 영문 제목의 낱말을 국문 제목과 맞춰 보는 데 쓴다.
GLOSSARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"risk\s+assessment", ("위험성평가",)),
    (r"occupational\s+safety\s+and\s+health\s+education|industrial\s+safety\s+and\s+health\s+education",
     ("산업안전보건교육", "안전보건교육")),
    (r"safety\s+and\s+health\s+education", ("안전보건교육", "산업안전보건교육")),
    (r"safety\s+education", ("안전교육",)),
    (r"special\s+education|special\s+training", ("특별교육",)),
    (r"safety\s+conscious\w*|safety\s+aware\w*", ("안전의식",)),
    (r"management\s+supervisor|managerial\s+supervisor|supervisor", ("관리감독자",)),
    (r"employer", ("사업주",)),
    (r"workplace|worksite", ("사업장",)),
    (r"field\s+operation|field\s+applica\w*|on[-\s]?site", ("현장",)),
    (r"small\s*(?:and\s*medium|[-\s]scale|business|enterprise)", ("중소", "소규모")),
    (r"construction", ("건설",)),
    (r"manufactur\w+", ("제조",)),
    (r"chemical", ("화학",)),
    (r"machin\w+", ("기계",)),
    (r"accident|disaster", ("재해", "사고")),
    (r"prevent\w+", ("예방",)),
    (r"improve\w+|enhance\w+", ("개선", "내실화", "향상", "고도화")),
    (r"effective\w*|efficien\w+", ("실효성", "효과", "효율")),
    (r"strengthen\w+|reinforce\w+", ("강화", "제고")),
    (r"train\w+|education", ("교육",)),
    (r"\bplan\b|\bmeasure\w*\b|\bscheme\b", ("방안",)),
    (r"system|institution|scheme", ("제도", "시스템")),
    (r"worker|employee|labor\w*", ("근로자", "노동자")),
    (r"health", ("보건",)),
    (r"safety", ("안전",)),
    (r"management", ("관리",)),
    (r"actual\s+condition|status|survey", ("실태",)),
    (r"analy\w+", ("분석",)),
    (r"polic\w+", ("정책",)),
    (r"guideline|guidance", ("지침",)),
    (r"standard|criteri\w+|regulation", ("기준", "규칙"),),
    (r"inspection", ("검사",)),
    (r"certif\w+|approval", ("인증", "승인")),
    (r"implement\w+|operat\w+", ("실시", "운영", "이행")),
)


@dataclass
class Report:
    no: str
    title: str
    authors_raw: str = ""
    year: Optional[str] = None
    terms: list[str] = field(default_factory=list)   # 맞아떨어진 국문 용어

    @property
    def url(self) -> str:
        return DETAIL.format(no=self.no)

    @property
    def authors(self) -> list[str]:
        s = re.sub(r"\([^)]*\)", " ", self.authors_raw or "")
        s = re.sub(r"외\s*\d*\s*[명인]?|등\s*\d*\s*[명인]?", " ", s)
        return [p.strip() for p in re.split(r"[,·，、\t]+", s) if p.strip()]

    def to_dict(self) -> dict:
        return {"no": self.no, "title": self.title, "authors_raw": self.authors_raw,
                "year": self.year, "terms": self.terms}


def mentions_kosha(text: str) -> bool:
    return bool(PUBLISHER_RE.search(text or ""))


def report_no(text: str) -> Optional[str]:
    m = REPORT_NO_RE.search(text or "")
    return m.group(1) if m else None


def surname_candidates(romanized: Optional[str]) -> tuple[str, ...]:
    if not romanized:
        return ()
    key = re.sub(r"[^a-z]", "", romanized.lower())
    return SURNAME.get(key, ())


def korean_terms(english_title: Optional[str]) -> list[str]:
    """영문 제목에 들어 있는 분야 용어를 국문 용어 후보로 바꾼다."""
    t = (english_title or "").lower()
    out: list[str] = []
    for pat, kos in GLOSSARY:
        if re.search(pat, t):
            out.append(kos[0] if len(kos) == 1 else "|".join(kos))
    return out


def _term_hits(korean_title: str, terms: list[str]) -> list[str]:
    hits = []
    for t in terms:
        for alt in t.split("|"):
            if alt and alt in korean_title:
                hits.append(alt)
                break
    return hits


async def search(client: httpx.AsyncClient, query: str = "", year: Optional[int] = None,
                 rows: int = 200) -> list[Report]:
    body = {
        "page": 1, "rowsPerPage": rows, "rschCd": "all", "rschRptpPlcyRschCd": "",
        "startDt": year or 1989, "endDt": year or 2026,
        "searchType": "all", "searchVal": query or "",
    }
    r = await client.post(API, json=body, headers=HEADERS, timeout=25.0)
    r.raise_for_status()
    payload = (r.json() or {}).get("payload") or {}
    out = []
    for x in payload.get("list") or []:
        out.append(Report(no=str(x.get("rschRptpNo") or ""),
                          title=(x.get("rschRptpTtl") or "").strip(),
                          authors_raw=(x.get("rschRptpRscrCn") or "").strip(),
                          year=str(x.get("rschRptpFlfmtYr") or "") or None))
    return out


def pick(reports: list[Report], surnames: tuple[str, ...], terms: list[str]) -> list[Report]:
    """성으로 거르고 분야 용어가 많이 맞는 순으로 돌려준다."""
    cands = []
    for rp in reports:
        if surnames and not any(a.startswith(s) for a in rp.authors for s in surnames):
            continue
        hits = _term_hits(rp.title, terms)
        if hits:
            rp.terms = hits
            cands.append(rp)
    cands.sort(key=lambda r: -len(r.terms))
    return cands
