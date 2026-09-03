# -*- coding: utf-8 -*-
"""배포용 실행 파일과 압축 꾸러미를 만든다.

실행:  .venv\\Scripts\\python build_dist.py     (또는 빌드.bat)
결과:  배포\\참고문헌 실존 확인.exe  +  참고문헌 실존 확인_v{버전}.zip
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

VERSION = "1.3"
ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(ROOT, "배포")
EXE_NAME = "참고문헌 실존 확인.exe"

READ_ME = """참고문헌 실존 확인  v{ver}
========================================

논문의 참고문헌이 실제로 존재하는 문헌인지 확인하고,
원문으로 갈 수 있는 링크(RISS 원문보기, DOI, 무료 PDF)를 붙여 주는 프로그램입니다.
AI가 지어낸 가짜 참고문헌이나 연도·저자 오기를 걸러내는 데 씁니다.


[ 실행 방법 ]

  "참고문헌 실존 확인.exe" 를 더블클릭하세요.
  검은 창이 뜨고 잠시 뒤 웹브라우저가 자동으로 열립니다.
  끝낼 때는 검은 창을 닫으면 됩니다.

  설치 과정은 없습니다. 이 파일 하나만 있으면 되고, USB에 담아 다녀도 됩니다.


[ 처음 실행할 때 파란 경고창이 뜬다면 ]

  "Windows의 PC 보호" 라는 파란 창이 뜰 수 있습니다.
  개발자 서명이 없는 프로그램에 윈도우가 붙이는 일반적인 경고입니다.

    [추가 정보] 를 누르고  ->  [실행] 을 누르면 됩니다.

  한 번 허용하면 다음부터는 뜨지 않습니다.


[ 쓰는 순서 ]

  1. 논문 파일을 창 안에 끌어다 놓습니다.
     PDF, DOCX, HWPX, TXT 를 읽습니다.
     구버전 .hwp 는 한글에서 .hwpx 나 PDF 로 저장한 뒤 넣으세요.
     참고문헌 목록만 있다면 '텍스트 붙여넣기' 탭을 쓰면 됩니다.

  2. 추출된 목록을 확인합니다. 한 줄이 한 문헌입니다.
     잘못 붙거나 나뉜 항목이 있으면 그 칸에서 직접 고칠 수 있습니다.

  3. [실존 여부 확인 시작] 을 누릅니다.
     결과가 나오는 대로 아래 표에 채워집니다.
     다 끝나면 [엑셀로 저장] 으로 내려받을 수 있습니다.

  4. 맨 아래 [APA 정렬 목록] 에서 정리된 참고문헌을 복사해 논문에 붙여넣습니다.


[ APA 정렬 목록 ]

  검증이 끝나면 APA 규칙에 맞춰 정렬된 목록이 만들어집니다.
  제1저자 기준으로 국문(가나다)을 먼저, 영문(ABC)을 뒤에 놓습니다.

  확인되지 않은 항목은 빨간색으로 표시됩니다.
  [서식 그대로 복사] 를 누르고 한글이나 워드에 붙여넣으면 빨간색이 그대로 따라갑니다.
  색 없이 글자만 필요하면 [글자만 복사] 를 쓰세요.

  번호 형식은 학교마다 다르므로 복사 전에 고를 수 있습니다.
      없음 / (1) / [1] / 1. / 1)

  '확인됨만 넣기' 를 켜면 확인된 문헌만 목록에 넣습니다.

  '확인된 서지로 교정' 을 켜면 조회된 서지로 APA 문장을 다시 만듭니다.
  다만 저자, 연도, 제목, 학술지, 권, 호, 쪽이 모두 확인된 항목에만 적용하고
  하나라도 불확실하면 원래 쓰신 문장을 그대로 둡니다.
  어설프게 고친 서지를 논문에 넣는 것이 원문을 두는 것보다 위험하기 때문입니다.


[ 판정 읽는 법 ]

  논문 심사에 쓰는 도구라 판정을 보수적으로 합니다.
  가짜를 '확인됨' 으로 통과시키는 쪽이 위험하고,
  진짜를 '확인 불가' 로 넘기는 쪽은 사람이 한 번 더 보면 되는 실수이기 때문입니다.

  확인됨      제목이 거의 같고 연도가 맞으며 저자나 게재지가 뒷받침됩니다.
  검토 필요    후보는 있으나 연도, 저자, 게재지 중 어긋난 것이 있습니다. 원문을 열어 대조하세요.
  확인 불가    조회한 곳에서 일치하는 항목을 찾지 못했습니다.
  검증 제외    법령, 고시처럼 서지 데이터베이스 대상이 아닌 자료입니다.

  '확인됨' 이 아닌 항목은 모두 사람이 직접 봐야 합니다.
  결과 위의 요약 줄에 그 건수가 나옵니다.

  '확인 불가' 가 곧 가짜라는 뜻은 아닙니다.
  단행본, 기관 보고서, 학술대회 발표문, 오래된 국내 문헌은 데이터베이스 수록률이 낮습니다.
  표에 함께 나오는 RISS, ScienceON, Google Scholar 검색 링크로 한 번 더 확인하세요.

  반대로 '확인됨' 이어도 권호와 페이지까지 맞는지는 원문에서 보셔야 합니다.


[ 주의 표시 ]

  판정 옆에 붙는 빨간 표시가 실제로 확인해야 할 지점을 알려 줍니다.

  DOI 제목 불일치   적힌 DOI 는 실재하지만 다른 논문의 것입니다. 지어낸 문헌에서 자주 나옵니다.
  DOI 없음         적힌 DOI 가 Crossref 에 등록되어 있지 않습니다.
  연도 불일치       재발행본을 인용했거나 연도를 잘못 적었습니다.
  저자 불일치       제목은 맞는데 저자가 다릅니다.
  게재지 불일치     제목은 맞는데 실린 학술지가 다릅니다.
  중복 기재         같은 문헌이 목록에 두 번 이상 올라와 있습니다.


[ 옵션 ]

  엄격 판정 (기본 켜짐)
      근거가 확실할 때만 '확인됨' 을 줍니다. 심사용으로 권장합니다.

  전수조사 (기본 켜짐)
      Crossref 에서 확실한 일치가 안 나오면
      RISS 의 여러 컬렉션과 짧게 줄인 검색어까지 넓혀 다시 찾습니다.
      영문으로 인용된 국내 문헌을 놓치지 않기 위한 것입니다.

  처음부터 RISS 도 함께 조회 (기본 꺼짐)
      켜면 모든 문헌을 처음부터 RISS 까지 조회합니다. 더 느려집니다.
      전수조사가 켜져 있으면 필요할 때 어차피 RISS 를 보므로 평소에는 꺼 두어도 됩니다.


[ 어디를 조회하나 ]

  국문 문헌         Crossref + RISS (국내학술논문, 학위논문, 단행본, 연구보고서)
  영문 문헌         Crossref, 못 찾으면 RISS
  위에서 못 찾은 것   마지막에 OpenAlex (하루 한도를 아끼려고 맨 뒤에 둡니다)
  영문 인용 국내 문헌  Korea, Seoul, KOSHA 같은 표시가 있으면 RISS 국내 컬렉션도 함께
  DOI 가 있는 문헌   Crossref 에 DOI 를 직접 조회해 등록된 제목과 대조
  웹 자료           적힌 주소에 실제로 접속되는지 확인
  법령             조회하지 않고 국가법령정보센터 링크만 제공

  API 키나 계정 없이 그대로 씁니다. 모두 공개된 정보만 조회합니다.
  실행할 때 AI 모델을 부르지 않으며, 대조는 문자열 유사도 계산으로 합니다.

  RISS 원문보기는 RISS 로그인이나 소속 기관 인증이 필요할 수 있습니다.
  무료인지 유료인지는 결과 표에 표시됩니다.


[ 알아둘 점 ]

  - 인터넷 연결이 필요합니다.
  - OpenAlex 는 키 없이 하루 100회까지 조회됩니다. (한국시간 오전 9시에 초기화)
    이 프로그램은 Crossref 와 RISS 로 확인되지 않은 문헌에만 OpenAlex 를 부르므로 보통은 넉넉합니다.
    많이 쓰신다면 openalex.org/pricing 에서 무료 키를 받아
    화면의 'OpenAlex 조회 한도 늘리기' 에 넣으세요. 하루 1,000회로 늘어납니다.
    키는 쓰시는 컴퓨터에만 저장됩니다.
    한도를 넘겨도 나머지 조회처로 계속 검증하며 화면 위에 알려 드립니다.
  - 문서 내용을 통째로 외부에 보내지 않습니다.
    참고문헌의 제목과 저자 같은 검색어만 조회에 사용합니다.
  - 한 번에 400건까지 확인합니다. 30건 기준 대략 30초에서 1분 걸립니다.
  - 조회 결과는 아래 폴더에 30일간 보관해, 같은 논문을 다시 검사하면 훨씬 빠릅니다.
        %LOCALAPPDATA%\\RefCheck\\cache
    결과가 이상하면 이 폴더를 지우고 다시 돌리세요.
  - 스캔한 이미지 PDF 는 글자가 없어 읽지 못합니다. 텍스트가 들어 있는 PDF 를 쓰세요.
  - 프로그램이 이미 켜져 있는 상태에서 다시 실행하면,
    새로 뜨지 않고 이미 열려 있는 화면을 브라우저로 띄워 줍니다.
"""


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"실패: {' '.join(cmd)}")


def main() -> None:
    py = sys.executable
    print("[1/4] 아이콘 생성")
    run([py, "make_icon.py"])

    print("[2/4] 실행 파일 빌드 (몇 분 걸립니다)")
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    pyi = os.path.join(os.path.dirname(py), "pyinstaller.exe")
    run([pyi, "--noconfirm", "--log-level", "WARN", "refcheck.spec"])

    exe = os.path.join(DIST, EXE_NAME)
    if not os.path.exists(exe):
        raise SystemExit("빌드 결과물을 찾지 못했습니다: " + exe)

    print("[3/4] 배포 폴더 구성")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    shutil.copy2(exe, os.path.join(OUT, EXE_NAME))
    readme = os.path.join(OUT, "사용법.txt")
    # 메모장에서 한글이 깨지지 않도록 BOM 붙인 UTF-8 + 윈도우 줄바꿈
    with open(readme, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(READ_ME.format(ver=VERSION))

    print("[4/4] 압축")
    zip_path = os.path.join(ROOT, f"참고문헌 실존 확인_v{VERSION}.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(os.listdir(OUT)):
            z.write(os.path.join(OUT, name), name)

    mb = lambda p: os.path.getsize(p) / 1024 / 1024
    print()
    print("완료")
    print(f"  실행 파일 : {os.path.join(OUT, EXE_NAME)}  ({mb(os.path.join(OUT, EXE_NAME)):.1f} MB)")
    print(f"  사용 설명 : {readme}")
    print(f"  배포 압축 : {zip_path}  ({mb(zip_path):.1f} MB)")


if __name__ == "__main__":
    main()
