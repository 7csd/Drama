param([int]$Port = 8787)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements-workbench.txt
if ($LASTEXITCODE -ne 0) { throw '安装工作台依赖失败' }
Push-Location -LiteralPath web
try {
    if (-not (Test-Path -LiteralPath node_modules)) {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw '安装前端依赖失败' }
    }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
Write-Host "帧序工作台：http://127.0.0.1:$Port/drama"
& .\.venv\Scripts\python.exe -m uvicorn workbench.api:app --host 127.0.0.1 --port $Port
