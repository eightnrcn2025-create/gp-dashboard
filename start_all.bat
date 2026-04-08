@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%USERPROFILE%\Desktop\gp活动看板
set LOGS_DIR=%PROJECT_DIR%\logs
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

echo ================================================
echo   Gamepark 看板
echo   项目路径: %PROJECT_DIR%
echo ================================================
echo.
echo 注：刷新功能已改为 GitHub Actions，无需本地服务。
echo     配置说明请查看 SETUP_REFRESH.md
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 python，请安装 Python
    pause & exit /b 1
)

cd /d "%PROJECT_DIR%"

REM ── 启动 api_server（port 5001，可选）────────────────────────
netstat -ano | findstr ":5001 " >nul 2>&1
if errorlevel 1 (
    echo [INFO] 启动 API 服务 (port 5001)...
    start /b python api_server.py > "%LOGS_DIR%\api_server.log" 2>&1
    timeout /t 2 /nobreak >nul
    echo [OK]  API 服务已启动 ^→ http://localhost:5001
) else (
    echo [INFO] API 服务已在运行
)

echo.

if exist "%PROJECT_DIR%\index.html" (
    start "" "%PROJECT_DIR%\index.html"
    echo [OK]  已打开 index.html
)

echo.
echo ================================================
echo   看板地址（GitHub Pages）：
echo   https://eightnrcn2025-create.github.io/gp-dashboard/
echo ================================================
echo.
pause
endlocal
