@echo off
REM ============================================================
REM spider_jp_worldlink 后端启动脚本 (Windows / cmd)
REM 用法:
REM   run.bat               启动开发服务（自动 reload）
REM   run.bat --no-reload   关闭热重载
REM   run.bat --port 9000   指定端口
REM   run.bat --init-db-only  仅初始化数据库
REM ============================================================

setlocal

set CONDA_ENV=spider_jp_worldlink
cd /d %~dp0

REM 如果未激活目标 conda 环境，则尝试激活
if /I not "%CONDA_DEFAULT_ENV%"=="%CONDA_ENV%" (
    echo [run.bat] activating conda env: %CONDA_ENV%
    call conda activate %CONDA_ENV%
    if errorlevel 1 (
        echo [run.bat] conda activate failed. Run "conda env create -f ..\environment.yml" first.
        exit /b 1
    )
)

if not exist .env (
    echo [run.bat] backend\.env not found. Copying from .env.example ...
    copy /Y .env.example .env >nul
    echo [run.bat] Please edit backend\.env (MySQL / Redis / FERNET_KEY) and re-run.
)

python run.py %*

endlocal
