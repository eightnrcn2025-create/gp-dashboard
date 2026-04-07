@echo off
chcp 65001 >nul
setlocal

set TASK_NAME=GameparkDashboardUpdate
set PROJECT_DIR=%USERPROFILE%\Desktop\gp活动看板
set PYTHON_CMD=python
set SCRIPT=%PROJECT_DIR%\update_data.py

echo ================================================
echo   Gamepark 看板 - 定时任务配置
echo ================================================
echo.

REM 检查 Python 是否可用
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 python，请先安装 Python 并添加到 PATH
    pause
    exit /b 1
)

REM 检查脚本是否存在
if not exist "%SCRIPT%" (
    echo [ERROR] 未找到脚本：%SCRIPT%
    echo         请确认项目已放置在桌面 gp活动看板 文件夹内
    pause
    exit /b 1
)

REM 删除旧任务（如存在）
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] 检测到已有同名任务，正在删除旧任务...
    schtasks /delete /tn "%TASK_NAME%" /f >nul
)

REM 创建新计划任务
REM   /sc DAILY    每天执行
REM   /st 08:00    早上 8 点
REM   /rl HIGHEST  以最高权限运行，避免网络访问受限
REM   /f           强制覆盖
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "cmd /c \"cd /d \"%PROJECT_DIR%\" && %PYTHON_CMD% update_data.py >> \"%PROJECT_DIR%\logs\update_log.txt\" 2>&1\"" ^
    /sc DAILY ^
    /st 08:00 ^
    /rl HIGHEST ^
    /f

if errorlevel 1 (
    echo.
    echo [ERROR] 定时任务创建失败，请以管理员身份运行此脚本
    pause
    exit /b 1
)

echo.
echo [OK] 定时任务创建成功！
echo.
echo   任务名称 : %TASK_NAME%
echo   执行时间 : 每天 08:00
echo   项目路径 : %PROJECT_DIR%
echo   日志文件 : %PROJECT_DIR%\logs\update_log.txt
echo.
echo 可通过"任务计划程序"查看和管理该任务
echo.

REM 询问是否立即执行一次
set /p RUN_NOW=是否立即执行一次更新？(y/n):
if /i "%RUN_NOW%"=="y" (
    echo.
    echo [INFO] 正在执行更新...
    cd /d "%PROJECT_DIR%"
    python update_data.py
    echo.
    echo [OK] 更新完成
)

pause
endlocal
