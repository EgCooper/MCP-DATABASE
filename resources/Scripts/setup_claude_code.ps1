$ErrorActionPreference = "Stop"

# The script lives in resources/Scripts; everything runs from the repo root.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $RootDir

# uv installs Python and the venv without admin rights and without touching the system Python.
$UvVersion = "0.12.24"
$PythonVersion = "3.13"
$UvInstallDir = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
$PythonBin = Join-Path $RootDir ".venv\Scripts\python.exe"
$PyvenvCfg = Join-Path $RootDir ".venv\pyvenv.cfg"

# Windows PowerShell does not stop when a native command fails, so check exit codes here.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo ($LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

$UvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($UvCommand) {
    $UvBin = $UvCommand.Path
} elseif (Test-Path (Join-Path $UvInstallDir "uv.exe")) {
    $UvBin = Join-Path $UvInstallDir "uv.exe"
} else {
    Write-Host "==> Instalando uv $UvVersion en $UvInstallDir..."
    $env:UV_INSTALL_DIR = $UvInstallDir
    # Separate process: the official installer calls exit on failure. Old Windows builds default to TLS 1.0.
    $Installer = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; " +
        "irm https://astral.sh/uv/$UvVersion/install.ps1 | iex"
    Invoke-Native "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Installer)
    $UvBin = Join-Path $UvInstallDir "uv.exe"
}

Write-Host "==> Instalando Python $PythonVersion (si falta)..."
Invoke-Native $UvBin @("python", "install", $PythonVersion)

# A .venv from an older setup points to the system Python; rebuild it with uv's Python.
$IsUvVenv = (Test-Path $PyvenvCfg) -and (Select-String -Path $PyvenvCfg -Pattern "^uv = " -Quiet)
if (-not (Test-Path $PythonBin) -or -not $IsUvVenv) {
    Write-Host "==> Creando entorno virtual (.venv) con Python $PythonVersion..."
    Invoke-Native $UvBin @("venv", "--clear", "--managed-python", "--python", $PythonVersion, ".venv")
}

Write-Host "==> Instalando dependencias..."
Invoke-Native $UvBin @("pip", "install", "--python", $PythonBin, "-e", ".")

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
