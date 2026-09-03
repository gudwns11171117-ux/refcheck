# -*- coding: utf-8 -*-
"""국가법령정보센터(법제처)에서 법령과 행정규칙(고시·훈령·예규·지침)을 확인한다.

법제처 Open API 는 등록(OC 발급)이 필요하지만, 국가법령정보센터가 화면에서 쓰는
검색 창구는 키 없이 조회된다. 이 파일은 그 창구만 쓴다.

- 법령(법률·시행령·시행규칙)  : https://www.law.go.kr/법령/<이름> 이 열리는지로 확인
- 행정규칙(고시·지침 등)       : 발령번호나 규칙명으로 목록을 받아 소관부처로 가린다

영문으로 인용된 고시도 잡을 수 있다. 인용문의 [2020-53] 같은 발령번호와
'Ministry of Employment and Labor' 같은 부처명만 있으면 국문 규칙명을 몰라도 찾아진다.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import quote

import httpx

BASE = "https://www.law.go.kr"
ADMRUL_LIST = BASE + "/LSW/admRulScListR.do?menuId=5&subMenuId=41&tabMenuId=183"
ADMRUL_VIEW = BASE + "/admRulLsInfoP.do?admRulSeq={seq}"
LAW_PAGE = BASE + "/법령/{name}"
ADMRUL_SEARCH_PAGE = BASE + "/LSW/admRulSc.do?menuId=5&subMenuId=41&query={q}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE + "/LSW/admRulSc.do?menuId=5&subMenuId=41",
}
POST_HEADERS = dict(HEADERS, **{"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})

_sem = asyncio.Semaphore(2)

# 발령번호: [2020-53] / 제2020-53호 / 2020-53
NOTICE_NO_RE = re.compile(r"[\[\(（]?\s*제?\s*((?:19|20)\d{2})\s*[-–]\s*(\d{1,4})\s*호?\s*[\]\)）]?")

# 영문으로 적힌 부처명을 국문으로
MINISTRY_EN: dict[str, str] = {
    "ministry of employment and labor": "고용노동부",
    "ministry of labor": "고용노동부",
    "ministry of land, infrastructure and transport": "국토교통부",
    "ministry of land infrastructure and transport": "국토교통부",
    "ministry of health and welfare": "보건복지부",
    "ministry of environment": "환경부",
    "ministry of education": "교육부",
    "ministry of trade, industry and energy": "산업통상자원부",
    "ministry of the interior and safety": "행정안전부",
    "ministry of public administration and security": "행정안전부",
    "ministry of oceans and fisheries": "해양수산부",
    "ministry of agriculture, food and rural affairs": "농림축산식품부",
    "ministry of science and ict": "과학기술정보통신부",
    "ministry of justice": "법무부",
    "ministry of economy and finance": "기획재정부",
    "ministry of gender equality and family": "여성가족부",
    "ministry of culture, sports and tourism": "문화체육관광부",
    "ministry of national defense": "국방부",
    "ministry of sme s and startups": "중소벤처기업부",
    "food and drug safety": "식품의약품안전처",
    "korea customs service": "관세청",
    "korea forest service": "산림청",
    "national fire agency": "소방청",
    "rural development administration": "농촌진흥청",
}
MINISTRY_KO_RE = re.compile(
    r"(고용노동부|국토교통부|보건복지부|환경부|교육부|산업통상자원부|행정안전부|해양수산부|"
    r"농림축산식품부|과학기술정보통신부|법무부|기획재정부|여성가족부|문화체육관광부|국방부|"
    r"중소벤처기업부|식품의약품안전처|관세청|산림청|소방청|농촌진흥청|국세청|경찰청|질병관리청)"
)

_ITEM_RE = re.compile(
    r'title="([^"]{8,300})"[^>]*onclick="javascript:showAdmRulCts\(\'(\d+)\'', re.S)
_TITLE_TAG_RE = re.compile(r"<title>([^<]{1,200})</title>")


@dataclass
class AdmRul:
    name: str                 # 규칙명
    seq: str                  # 상세 페이지 식별자
    raw_title: str            # 대괄호 정보까지 붙은 원본 문자열
    ministry: Optional[str] = None
    notice_no: Optional[str] = None    # '2020-53'
    effective: Optional[str] = None    # 시행일

    @property
    def url(self) -> str:
        return ADMRUL_VIEW.format(seq=self.seq)

    def to_dict(self) -> dict:
        return asdict(self)


def ministry_of(text: str) -> Optional[str]:
    """인용문에서 소관부처를 국문으로 뽑는다. 영문 표기도 알아본다."""
    m = MINISTRY_KO_RE.search(text or "")
    if m:
        return m.group(1)
    low = re.sub(r"[^a-z ]", " ", (text or "").lower())
    low = re.sub(r"\s+", " ", low)
    for en, ko in MINISTRY_EN.items():
        if en in low:
            return ko
    return None


def notice_no(text: str) -> Optional[str]:
    m = NOTICE_NO_RE.search(text or "")
    return f"{m.group(1)}-{int(m.group(2))}" if m else None


def _parse_items(html: str) -> list[AdmRul]:
    out: list[AdmRul] = []
    for m in _ITEM_RE.finditer(html):
        raw = re.sub(r"\s+", " ", m.group(1).replace("\r", " ")).strip()
        seq = m.group(2)
        name = raw.split("[")[0].strip()
        mn = MINISTRY_KO_RE.search(raw)
        no = NOTICE_NO_RE.search(raw)
        eff = re.search(r"시행\s*([0-9]{4}\.\s*[0-9]{1,2}\.\s*[0-9]{1,2}\.?)", raw)
        out.append(AdmRul(name, seq, raw,
                          mn.group(1) if mn else None,
                          f"{no.group(1)}-{int(no.group(2))}" if no else None,
                          eff.group(1).replace(" ", "") if eff else None))
    return out


async def search_admrul(client: httpx.AsyncClient, q: str, section: str = "admRulNm",
                        outmax: int = 100) -> list[AdmRul]:
    """행정규칙 목록을 받는다. section 은 규칙명(admRulNm) 기준."""
    body = {"q": q, "section": section, "outmax": str(outmax), "pg": "1",
            "dtlYn": "N", "admType": "N", "admRulSeq": "0"}
    async with _sem:
        r = await client.post(ADMRUL_LIST, data=body, headers=POST_HEADERS, timeout=25.0,
                              follow_redirects=True)
        await asyncio.sleep(0.2)
    r.raise_for_status()
    return _parse_items(r.text)


async def law_exists(client: httpx.AsyncClient, name: str) -> Optional[str]:
    """법률·시행령·시행규칙이 실재하는지. 있으면 정식 명칭을 돌려준다."""
    name = re.sub(r"\s+", "", name or "")
    if len(name) < 3:
        return None
    async with _sem:
        r = await client.get(LAW_PAGE.format(name=quote(name)), headers=HEADERS,
                             timeout=25.0, follow_redirects=True)
        await asyncio.sleep(0.2)
    if r.status_code != 200:
        return None
    m = _TITLE_TAG_RE.search(r.text)
    title = m.group(1).strip() if m else ""
    if not title or "오류" in title or "검색결과" in title:
        return None
    return title


def search_page_url(q: str) -> str:
    return ADMRUL_SEARCH_PAGE.format(q=quote(q))
