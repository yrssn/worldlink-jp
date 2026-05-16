# ============================================================
# spider_jp_worldlink 后端启动脚本 (PowerShell)
# 用法:
#   .\run.ps1                     # 启动开发服务（自动 reload）
#   .\run.ps1 --no-reload         # 关闭热重载
#   .\run.ps1 --port 9000         # 指定端口
#   .\run.ps1 --init-db-only      # 仅初始化数据库
# ============================================================

$ErrorActionPreference = "Stop"

$CondaEnv = "spider_jp_worldlink"
Set-Location -Path $PSScriptRoot

# 激活 conda 环境（如未激活）
if ($env:CONDA_DEFAULT_ENV -ne $CondaEnv) {
    Write-Host "[run.ps1] activating conda env: $CondaEnv"
    try {
        conda activate $CondaEnv
    } catch {
        Write-Host "[run.ps1] conda activate failed. Run 'conda env create -f ..\environment.yml' first." -ForegroundColor Red
        exit 1
    }
}

# 检查 .env
if (-not (Test-Path ".\.env")) {
    Write-Host "[run.ps1] backend\.env not found. Copying from .env.example ..." -ForegroundColor Yellow
    Copy-Item ".\.env.example" ".\.env"
    Write-Host "[run.ps1] Please edit backend\.env (MySQL / Redis / FERNET_KEY) and re-run." -ForegroundColor Yellow
}

python run.py @args
