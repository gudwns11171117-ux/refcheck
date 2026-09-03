# -*- coding: utf-8 -*-
"""참고문헌 실존 확인 툴 - 로컬 웹 서버.

실행:  .venv\\Scripts\\python app.py   (또는 실행.bat)
브라우저: http://127.0.0.1:8765
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refcheck.export import to_xlsx                       # noqa: E402
from refcheck.extract import extract_references, split_pasted_text   # noqa: E402
from refcheck.parse import parse_reference                # noqa: E402
from refcheck.paths import resource_path                  # noqa: E402
from refcheck.verify import Options, unavailable_sources, verify_all   # noqa: E402

STATIC = resource_path("static")
DEFAULT_PORT = int(os.environ.get("REFCHECK_PORT", "8765"))
MAX_UPLOAD = 60 * 1024 * 1024
PING_TOKEN = "refcheck-local"

app = FastAPI(title="참고문헌 실존 확인", docs_url=None, redoc_url=None)
JOBS: dict[str, dict] = {}


class TextIn(BaseModel):
    text: str


class VerifyIn(BaseModel):
    refs: list[str]
    options: dict = {}
    source_name: str = ""


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"), media_type="text/html")


@app.get("/api/ping")
async def api_ping():
    """이미 떠 있는 우리 서버인지 구별하는 표식(중복 실행 방지용)."""
    return {"app": PING_TOKEN}


def _pack_refs(raw_refs: list[str]) -> list[dict]:
    return [parse_reference(i + 1, r).to_dict() for i, r in enumerate(raw_refs)]


@app.post("/api/extract")
async def api_extract(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "파일이 너무 큽니다(60MB 제한).")
    if not data:
        raise HTTPException(400, "빈 파일입니다.")
    try:
        r = await asyncio.to_thread(extract_references, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"문서를 읽는 중 오류: {type(e).__name__}: {e}")
    return {
        "refs": _pack_refs(r.refs),
        "meta": {
            "filename": file.filename, "pages": r.pages, "heading_found": r.heading_found,
            "heading_text": r.heading_text, "method": r.method, "warnings": r.warnings,
            "section_chars": len(r.section_text),
        },
    }


@app.post("/api/extract-text")
async def api_extract_text(inp: TextIn):
    refs = split_pasted_text(inp.text or "")
    return {"refs": _pack_refs(refs), "meta": {"filename": "(붙여넣은 텍스트)", "pages": 0, "heading_found": True,
                                                 "heading_text": "", "method": "paste", "warnings": [], "section_chars": len(inp.text)}}


@app.post("/api/verify")
async def api_verify(inp: VerifyIn):
    refs = [r.strip() for r in inp.refs if r and r.strip()]
    if not refs:
        raise HTTPException(400, "검증할 참고문헌이 없습니다.")
    if len(refs) > 400:
        raise HTTPException(400, "한 번에 400건까지만 검증할 수 있습니다.")
    o = inp.options or {}
    # 논문 심사용이므로 엄격 판정과 전수조사를 기본값으로 둔다
    opts = Options(riss_all=bool(o.get("riss_all", False)), check_urls=bool(o.get("check_urls", True)),
                   strict=bool(o.get("strict", True)), exhaustive=bool(o.get("exhaustive", True)))
    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "status": "running", "total": len(refs), "done": 0, "results": [None] * len(refs),
           "started": time.time(), "finished": None, "source_name": inp.source_name, "error": None}
    JOBS[job_id] = job

    def cb(i, res):
        job["results"][i] = res.to_dict()
        job["done"] += 1

    async def run():
        try:
            done = await verify_all(refs, opts, cb)
            # 중복 기재 표시는 전체가 끝난 뒤에 붙으므로 마지막에 한 번 더 옮겨 담는다
            for i, r in enumerate(done):
                job["results"][i] = r.to_dict()
            job["unavailable"] = unavailable_sources()
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
        job["finished"] = time.time()

    asyncio.create_task(run())
    # 오래된 작업 정리
    for k in [k for k, v in JOBS.items() if v["finished"] and time.time() - v["finished"] > 6 * 3600]:
        JOBS.pop(k, None)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    results = [r for r in job["results"] if r is not None]
    return {"id": job_id, "status": job["status"], "total": job["total"], "done": job["done"],
            "elapsed": round((job["finished"] or time.time()) - job["started"], 1),
            "results": results, "error": job["error"], "unavailable": job.get("unavailable") or {}}


@app.get("/api/jobs/{job_id}/export.xlsx")
async def api_export(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    results = [r for r in job["results"] if r is not None]
    data = to_xlsx(results, job.get("source_name") or "")
    base = os.path.splitext(os.path.basename(job.get("source_name") or "참고문헌"))[0] or "참고문헌"
    fname = f"{base}_참고문헌검증.xlsx"
    headers = {"Content-Disposition": f"attachment; filename=\"refcheck.xlsx\"; filename*=UTF-8''{quote(fname)}"}
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


def _open_browser(port: int, delay: float = 1.2):
    time.sleep(delay)
    try:
        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:  # noqa: BLE001
        pass


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _already_running(port: int) -> bool:
    """그 포트에 떠 있는 것이 이 프로그램의 다른 인스턴스인지 확인."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == PING_TOKEN
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _pick_port() -> int:
    for p in range(DEFAULT_PORT, DEFAULT_PORT + 12):
        if _port_free(p):
            return p
    return DEFAULT_PORT


def main() -> int:
    quiet = os.environ.get("REFCHECK_NO_BROWSER") == "1" or "--no-browser" in sys.argv

    # 이미 실행 중이면 새로 띄우지 않고 그 창만 열어 준다
    if not _port_free(DEFAULT_PORT) and _already_running(DEFAULT_PORT):
        print(f"이미 실행 중입니다. 브라우저에서 http://127.0.0.1:{DEFAULT_PORT} 를 여세요.")
        if not quiet:
            _open_browser(DEFAULT_PORT, delay=0.1)
        return 0

    port = _pick_port()
    if not quiet:
        threading.Thread(target=_open_browser, args=(port,), daemon=True).start()
    # 한글 콘솔(CP949)에서 인코딩 오류가 나지 않도록 특수문자는 쓰지 않는다
    print()
    print(f"  참고문헌 실존 확인 툴이 실행 중입니다.")
    print(f"  브라우저에서 열린 주소 : http://127.0.0.1:{port}")
    print(f"  끝낼 때는 이 창을 닫으세요.")
    print()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:  # noqa: BLE001 - exe 로 실행 시 창이 즉시 닫히지 않게 한다
        import traceback
        traceback.print_exc()
        print()
        print(f"  [오류] 프로그램을 시작하지 못했습니다: {type(e).__name__}: {e}")
        try:
            input("  엔터를 누르면 창이 닫힙니다. ")
        except EOFError:
            pass
        sys.exit(1)
