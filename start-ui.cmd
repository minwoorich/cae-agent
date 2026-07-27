@echo off
setlocal

rem 어느 위치에서 실행하더라도 저장소 루트에서 UI를 시작합니다.
cd /d "%~dp0"

set "UI_HOST=127.0.0.1"
set "UI_PORT=8765"
echo.
echo CAE Agent UI
echo Address: http://%UI_HOST%:%UI_PORT%
echo Host:    %UI_HOST%
echo Port:    %UI_PORT%
echo.

rem 로컬 서버가 뜰 시간을 조금 준 뒤 기본 브라우저를 엽니다.
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://%UI_HOST%:%UI_PORT%'"

rem NiceGUI가 브라우저 탭을 중복으로 열지 않도록 --no-browser로 실행합니다.
".venv\Scripts\cae-agent.exe" ui --no-browser --port %UI_PORT%

rem 시작 오류를 사용자가 확인할 수 있도록 창을 바로 닫지 않습니다.
echo.
echo CAE Agent UI server has stopped.
pause
