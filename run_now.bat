@echo off
chcp 65001 >nul
setlocal

set PROJECT_DIR=%USERPROFILE%\Desktop\gp活动看板

echo ================================================
echo   Gamepark 看板 - 立即执行数据更新
echo   正在抓取昨日数据，请稍候...
echo ================================================
echo.

REM 切换到项目目录
cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo [ERROR] 无法进入项目目录：%PROJECT_DIR%
    pause
    exit /b 1
)

REM 检查 Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 python，请安装 Python 并添加到 PATH
    pause
    exit /b 1
)

REM 检查脚本
if not exist "update_data.py" (
    echo [ERROR] 未找到 update_data.py
    pause
    exit /b 1
)

echo [INFO] 开始时间：%DATE% %TIME%
echo [INFO] 项目路径：%PROJECT_DIR%
echo.
echo ------------------------------------------------

python update_data.py

echo ------------------------------------------------
echo.

if errorlevel 1 (
    echo [ERROR] 更新执行过程中出现错误，请查看日志：
    echo         %PROJECT_DIR%\logs\update_log.txt
) else (
    echo [OK] 更新完成
    echo [OK] 结束时间：%DATE% %TIME%
    echo [OK] 数据文件：%PROJECT_DIR%\data\data.json
)

echo.
pause
endlocal
