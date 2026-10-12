$ErrorActionPreference = "Stop"

# The script lives in resources/Scripts; everything runs from the repo root.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $RootDir

$PythonBin = Join-Path $RootDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonBin)) {
    Write-Host "==> Creando entorno virtual (.venv)..."
    python -m venv .venv
}

Write-Host "==> Instalando dependencias..."
& $PythonBin -m pip install --upgrade pip | Out-Null
& $PythonBin -m pip install -e . | Out-Null

$EnvFile = Join-Path $RootDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "==> No existe .env. Copiando .env.example -> .env"
    Copy-Item (Join-Path $RootDir ".env.example") $EnvFile
}

Write-Host ""
Write-Host "==> Entorno listo. Antes de continuar:"
Write-Host "    1. Edita $EnvFile e inserta las credenciales de las bases que vayas a usar."
Write-Host "    2. Registra cada MCP con:"
Write-Host "         claude mcp add <nombre> -- `"$PythonBin`" -m <modulo>"
Write-Host "       (ej: claude mcp add mysql -- `"$PythonBin`" -m mcp_mysql)"
