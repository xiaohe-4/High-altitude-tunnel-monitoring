@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo 未找到 .venv，请先在项目目录执行：
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
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
"%PY%" server.py
