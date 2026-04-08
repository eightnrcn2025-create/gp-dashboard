@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%USERPROFILE%\Desktop\gp活动看板
set API_LOG=%PROJECT_DIR%\logs\api_server.log
set PID_FILE=%PROJECT_DIR%\logs\api_server.pid

if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"

echo ================================================
echo   Gamepark 看板 - 一键启动
echo   项目路径: %PROJECT_DIR%
echo ================================================
echo.

REM ── 检查 Python ──────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 python，请安装 Python 并添加到 PATH
    pause
    exit /b 1
)

REM ── 检查端口 5001 ────────────────────────────────────────────
netstat -ano | findstr ":5001 " >nul 2>&1
if errorlevel 1 (
    echo [INFO] 启动 API 服务 (port 5001)...
    cd /d "%PROJECT_DIR%"
    start /b python api_server.py >> "%API_LOG%" 2>&1
    timeout /t 2 /nobreak >nul
    echo [OK]  API 服务已在后台启动 ^→ http://localhost:5001
) else (
    echo [WARN] 端口 5001 已被占用，跳过启动 API 服务
)

echo.

REM ── 打开看板页面 ─────────────────────────────────────────────
if exist "%PROJECT_DIR%\index.html" (
    echo [INFO] 打开看板页面...
    start "" "%PROJECT_DIR%\index.html"
    echo [OK]  index.html 已在浏览器中打开
) else (
    echo [WARN] 未找到 index.html
)

echo.
echo ================================================
echo   API 服务: http://localhost:5001/api/status
echo ================================================
echo.
echo 如需立即抓取数据，运行：
echo   python update_data.py
echo.
pause
endlocal
