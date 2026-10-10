@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "MODE=venv"
if not exist "%~dp0.venv\Scripts\python.exe" set "MODE=py"
if "%MODE%"=="py" (
  py -3 -c "import fastapi,uvicorn" >nul 2>&1
  if errorlevel 1 (
    echo 未找到 .venv，本机 Python 也缺少 fastapi。
    echo 请在项目目录执行：
    echo   py -3 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
  )
  echo 未找到 .venv，改用本机 Python 启动。
)

if not exist "%~dp0.env" (
  if exist "%~dp0.env.example" (
    copy /y "%~dp0.env.example" "%~dp0.env" >nul
    echo 已根据 .env.example 生成 .env，请填入 MOMA_API_KEY 后再调用模型。
  )
)

netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  echo 服务已在运行： http://localhost:8000
  start "" http://localhost:8000
  exit /b 0
)

echo 正在启动监测页面： http://localhost:8000
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"
if "%MODE%"=="py" (
  py -3 server.py
) else (
  "%~dp0.venv\Scripts\python.exe" server.py
)
if errorlevel 1 pause
