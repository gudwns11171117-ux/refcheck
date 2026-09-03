# -*- coding: utf-8 -*-
"""참고문헌 실존 확인 툴 - 핵심 패키지.

extract  문서에서 참고문헌 목록 뽑기
parse    항목에서 제목·저자·연도·DOI 분해
riss     RISS 검색 결과 읽기
verify   Crossref·OpenAlex·RISS 대조와 판정
export   엑셀 저장
cache    조회 결과 임시 보관
paths    소스 실행과 exe 실행의 경로 차이 흡수
"""

__all__ = ["extract", "parse", "riss", "verify", "export", "cache", "paths"]
