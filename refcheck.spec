# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 설정. 단일 exe 로 묶는다.

빌드:  .venv\\Scripts\\pyinstaller --noconfirm refcheck.spec
"""

# uvicorn 은 실행 중에 모듈 이름을 문자열로 불러오므로 PyInstaller 가 자동으로 찾지 못한다.
hidden = [
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
    "encodings.cp949", "encodings.euc_kr", "encodings.utf_16",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[("static", "static")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pydoc_data", "PyInstaller", "pip"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="참고문헌 실존 확인",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)
