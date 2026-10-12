$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonBin = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonBin)) {
    Write-Host "==> Creando entorno virtual (.venv)..."
    python -m venv .venv
}

Write-Host "==> Instalando dependencias..."
& (Join-Path $ScriptDir ".venv\Scripts\pip.exe") install --upgrade pip | Out-Null
& (Join-Path $ScriptDir ".venv\Scripts\pip.exe") install -e . | Out-Null

$EnvFile = Join-Path $ScriptDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "==> No existe .env. Copiando .env.example -> .env"
    Copy-Item (Join-Path $ScriptDir ".env.example") $EnvFile
}

Write-Host ""
Write-Host "==> Entorno listo. Antes de continuar:"
Write-Host "    1. Edita $EnvFile e inserta las credenciales de las bases que vayas a usar."
Write-Host "    2. Registra cada MCP con:"
Write-Host "         claude mcp add <nombre> -- `"$PythonBin`" -m <modulo>"
Write-Host "       (ej: claude mcp add mysql -- `"$PythonBin`" -m mcp_mysql)"
