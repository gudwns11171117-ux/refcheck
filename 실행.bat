@echo off
chcp 949 >nul 2>nul
cd /d "%~dp0"
title 참고문헌 실존 확인 툴

where uv >nul 2>nul
if errorlevel 1 goto nouv

if exist ".venv\Scripts\python.exe" goto run

echo.
echo  처음 실행입니다. 파이썬 환경을 준비합니다. 1~2분 걸립니다.
echo.
uv venv --python 3.13 .venv
if errorlevel 1 goto err
uv pip install --python .venv -r requirements.txt
if errorlevel 1 goto err

:run
echo.
echo  참고문헌 실존 확인 툴을 시작합니다.
echo  잠시 후 브라우저가 열립니다.  주소: http://127.0.0.1:8765
echo  끝낼 때는 이 창을 닫으세요.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto err
exit /b 0

:nouv
echo.
echo  [오류] uv 가 설치되어 있지 않습니다.
echo  아래 한 줄을 PowerShell 에 붙여넣어 설치한 뒤 다시 실행하세요.
echo.
echo    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
echo.
pause
exit /b 1

:err
echo.
echo  [오류] 실행에 실패했습니다. 위에 나온 메시지를 확인하세요.
echo  인터넷 연결을 확인하고 다시 실행해 보세요.
echo.
pause
exit /b 1
