@echo off
chcp 949 >nul 2>nul
cd /d "%~dp0"
title 배포용 실행 파일 만들기

if not exist ".venv\Scripts\python.exe" goto noenv

echo.
echo  배포용 실행 파일을 만듭니다. 몇 분 걸립니다.
echo.
".venv\Scripts\python.exe" build_dist.py
if errorlevel 1 goto err
echo.
echo  끝났습니다. '배포' 폴더와 zip 파일을 확인하세요.
echo.
pause
exit /b 0

:noenv
echo.
echo  [오류] 개발 환경(.venv)이 없습니다. 먼저 실행.bat 을 한 번 실행하세요.
echo.
pause
exit /b 1

:err
echo.
echo  [오류] 빌드에 실패했습니다. 위에 나온 메시지를 확인하세요.
echo.
pause
exit /b 1
