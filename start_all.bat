@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%USERPROFILE%\Desktop\gp活动看板
set LOGS_DIR=%PROJECT_DIR%\logs
set REFRESH_LOG=%LOGS_DIR%\refresh_server.log
set API_LOG=%LOGS_DIR%\api_server.log

if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

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

cd /d "%PROJECT_DIR%"

REM ── 启动 refresh_server（port 5002）──────────────────────────
netstat -ano | findstr ":5002 " >nul 2>&1
if errorlevel 1 (
    echo [INFO] 启动刷新服务 (port 5002)...
    start /b python refresh_server.py > "%REFRESH_LOG%" 2>&1
    timeout /t 2 /nobreak >nul
    echo [OK]  刷新服务已启动 ^→ http://localhost:5002
) else (
    echo [WARN] 端口 5002 已被占用，跳过启动刷新服务
)

REM ── 启动 api_server（port 5001）──────────────────────────────
netstat -ano | findstr ":5001 " >nul 2>&1
if errorlevel 1 (
    echo [INFO] 启动 API 服务 (port 5001)...
    start /b python api_server.py > "%API_LOG%" 2>&1
    timeout /t 2 /nobreak >nul
    echo [OK]  API 服务已启动 ^→ http://localhost:5001
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
echo   刷新服务: http://localhost:5002/ping
echo   API 服务:  http://localhost:5001/api/status
echo ================================================
echo.
echo 点击看板右上角"立即刷新"可触发实时数据更新
echo.
pause
endlocal
