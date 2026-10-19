# Usage: setup_claude_code.ps1 [motores...]   e.g. "mysql oracle", "1,4", "todos" or "ninguno".
# Without arguments it asks which engines to register in Claude Code.
$EngineArgs = @($args)

$ErrorActionPreference = "Stop"
# Invoke-WebRequest in Windows PowerShell is very slow while drawing its progress bar.
$ProgressPreference = "SilentlyContinue"
# Old Windows builds default to TLS 1.0, which python.org and astral.sh reject.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# The script lives in resources/Scripts; everything runs from the repo root.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $RootDir

# uv creates the venv and installs packages without admin rights.
$UvVersion = "0.12.24"
$UvInstallDir = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }

# Python comes from python.org, not from uv: its files are signed by the Python Software
# Foundation, while uv's builds are unsigned and Smart App Control blocks them.
$PythonVersion = "3.13"
$PythonPatchVersion = "3.13.16"
$PythonArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
$PythonDirName = "Python" + ($PythonVersion -replace "\.", "") + $(if ($PythonArch -eq "arm64") { "-arm64" } else { "" })
$PythonHome = Join-Path $env:LOCALAPPDATA "Programs\Python\$PythonDirName"
$BasePython = Join-Path $PythonHome "python.exe"

$PythonBin = Join-Path $RootDir ".venv\Scripts\python.exe"
$PyvenvCfg = Join-Path $RootDir ".venv\pyvenv.cfg"
$EnvFile = Join-Path $RootDir ".env"

$Engines = @(
    [pscustomobject]@{ Name = "mysql"; Prefix = "MYSQL"; Label = "MySQL / osTicket" },
    [pscustomobject]@{ Name = "oracle"; Prefix = "ORACLE"; Label = "Oracle" },
    [pscustomobject]@{ Name = "postgresql"; Prefix = "POSTGRES"; Label = "PostgreSQL" },
    [pscustomobject]@{ Name = "sqlserver"; Prefix = "SQLSERVER"; Label = "SQL Server (requiere ODBC Driver 18 for SQL Server)" },
    [pscustomobject]@{ Name = "informix"; Prefix = "INFORMIX"; Label = "Informix (requiere IBM Informix Client SDK)" }
)
$AllEngines = @($Engines | ForEach-Object { $_.Name })

# Windows PowerShell does not stop when a native command fails, so check exit codes here.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo ($LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

# Runs a native command and returns its exit code and output; stderr does not stop the script.
function Invoke-Capture {
    param([string]$Exe, [string[]]$Arguments)
    $ErrorActionPreference = "Continue"
    $Output = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($Output -join "`n") }
}

function Test-SmartAppControlOn {
    # 0 = off, 1 = on (blocks), 2 = evaluation (does not block).
    $Policy = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy" -Name "VerifiedAndReputablePolicyState" -ErrorAction SilentlyContinue
    return [bool]($Policy -and $Policy.VerifiedAndReputablePolicyState -eq 1)
}

# Engines with at least one uncommented value in .env.
function Get-ConfiguredEngines {
    if (-not (Test-Path $EnvFile)) { return "" }
    $Lines = @(Get-Content $EnvFile)
    $Found = foreach ($Engine in $Engines) {
        if ($Lines -match "^$($Engine.Prefix)_[A-Z0-9_]+=.") { $Engine.Name }
    }
    return (@($Found) -join " ")
}

# Turns "1,4", "mysql sqlserver", "todos" or "ninguno" into engine names; $null on an unknown option.
function ConvertTo-EngineList {
    param([string]$Text)
    $Names = New-Object System.Collections.Generic.List[string]
    foreach ($Token in ($Text.ToLower() -split "[,\s]+")) {
        if (-not $Token) { continue }
        if ($Token -in "todos", "all") { return ($AllEngines -join " ") }
        if ($Token -in "ninguno", "none", "no", "n") { return "" }
        if ($Token -match "^\d+$" -and [int]$Token -ge 1 -and [int]$Token -le $AllEngines.Count) {
            $Name = $AllEngines[[int]$Token - 1]
        } elseif ($Token -in $AllEngines) {
            $Name = $Token
        } else {
            Write-Host "    Opcion no valida: $Token"
            return $null
        }
        if (-not $Names.Contains($Name)) { $Names.Add($Name) }
    }
    return ($Names -join " ")
}

function Register-Engine {
    param([string]$Name)
    $Replaced = ""
    # Drop older registrations: a stale path, or a per-folder one that would hide the user-wide one.
    foreach ($Scope in "user", "local") {
        if ((Invoke-Capture $ClaudeBin @("mcp", "remove", "--scope", $Scope, $Name)).ExitCode -eq 0) {
            $Replaced = " (reemplaza el registro anterior)"
        }
    }
    $Add = Invoke-Capture $ClaudeBin @("mcp", "add", "--scope", "user", $Name, "--", $PythonBin, "-m", "mcp_$Name")
    if ($Add.ExitCode -ne 0) {
        Write-Host "    ERROR ${Name}: claude mcp add fallo: $($Add.Output)"
        return $false
    }
    # "claude mcp get" starts the server once; it does not need the database credentials.
    $Status = (Invoke-Capture $ClaudeBin @("mcp", "get", $Name)).Output -split "`n" |
        Where-Object { $_ -match "Status:" } | Select-Object -First 1
    $Status = "$Status".Trim()
    if (-not $Status -or $Status -match "Failed") {
        Write-Host "    AVISO ${Name}: registrado, pero Claude Code no pudo iniciarlo. $Status"
        return $false
    }
    if ($Status -match "Connected") {
        Write-Host "    OK    ${Name}: registrado y conectado$Replaced"
    } else {
        Write-Host "    AVISO ${Name}: registrado, estado: $Status"
    }
    return $true
}

# Ask first, so the rest of the setup runs unattended.
$Selection = ""
if ($EngineArgs.Count -gt 0) {
    $Selection = ConvertTo-EngineList ($EngineArgs -join " ")
    if ($null -eq $Selection) { exit 1 }
} elseif (-not [Console]::IsInputRedirected) {
    $Default = Get-ConfiguredEngines
    if (-not $Default) { $Default = "mysql" }
    Write-Host "==> Que motores vas a usar? Despues de instalar te pedire sus datos de conexion y los registrare en Claude Code."
    for ($i = 0; $i -lt $Engines.Count; $i++) {
        Write-Host ("    {0}) {1,-11} {2}" -f ($i + 1), $Engines[$i].Name, $Engines[$i].Label)
    }
    Write-Host "    Escribe numeros o nombres separados por coma (ej: 1,4), 'todos' o 'ninguno'."
    do {
        $Answer = Read-Host "    [Enter = $Default]"
        $Selection = if ("$Answer".Trim()) { ConvertTo-EngineList $Answer } else { $Default }
    } while ($null -eq $Selection)
    Write-Host ""
}
$Selected = @("$Selection" -split " " | Where-Object { $_ })

$UvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($UvCommand) {
    $UvBin = $UvCommand.Path
} elseif (Test-Path (Join-Path $UvInstallDir "uv.exe")) {
    $UvBin = Join-Path $UvInstallDir "uv.exe"
} else {
    Write-Host "==> Instalando uv $UvVersion en $UvInstallDir..."
    $env:UV_INSTALL_DIR = $UvInstallDir
    # Separate process: the official installer calls exit on failure.
    $Installer = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; " +
        "irm https://astral.sh/uv/$UvVersion/install.ps1 | iex"
    Invoke-Native "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Installer)
    $UvBin = Join-Path $UvInstallDir "uv.exe"
}

if (Test-Path $BasePython) {
    Write-Host "==> Usando Python oficial ya instalado en $PythonHome"
} else {
    Write-Host "==> Instalando Python $PythonPatchVersion oficial (python.org) en $PythonHome..."
    $InstallerName = "python-$PythonPatchVersion-$PythonArch.exe"
    $InstallerPath = Join-Path $env:TEMP $InstallerName
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonPatchVersion/$InstallerName" -OutFile $InstallerPath -UseBasicParsing

    $Signature = Get-AuthenticodeSignature $InstallerPath
    if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        Remove-Item $InstallerPath -ErrorAction SilentlyContinue
        throw "El instalador descargado no tiene una firma valida de la Python Software Foundation."
    }

    # Per-user install: no admin rights, no PATH changes, no file associations.
    $InstallerArgs = "/quiet InstallAllUsers=0 TargetDir=`"$PythonHome`" PrependPath=0 Include_launcher=0 " +
        "Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0 AssociateFiles=0"
    $Process = Start-Process -FilePath $InstallerPath -ArgumentList $InstallerArgs -Wait -PassThru
    Remove-Item $InstallerPath -ErrorAction SilentlyContinue
    # 3010 = installed, reboot recommended.
    if ($Process.ExitCode -ne 0 -and $Process.ExitCode -ne 3010) {
        throw "El instalador de Python termino con codigo $($Process.ExitCode)."
    }
    if (-not (Test-Path $BasePython)) {
        throw "No se encontro $BasePython despues de instalar Python."
    }
}

# A .venv from an older setup may use the system Python or uv's unsigned Python; rebuild it.
$VenvHome = ""
if (Test-Path $PyvenvCfg) {
    $HomeLine = Select-String -Path $PyvenvCfg -Pattern "^home\s*=\s*(.+)$" | Select-Object -First 1
    if ($HomeLine) { $VenvHome = $HomeLine.Matches[0].Groups[1].Value.Trim().TrimEnd("\") }
}
if (-not (Test-Path $PythonBin) -or $VenvHome -ne $PythonHome.TrimEnd("\")) {
    Write-Host "==> Creando entorno virtual (.venv) con $BasePython..."
    try {
        Invoke-Native $UvBin @("venv", "--clear", "--python", $BasePython, ".venv")
    } catch {
        throw "$_`nSi el .venv esta en uso, cierra Claude Code y VSCode y vuelve a ejecutar el setup."
    }
}

Write-Host "==> Instalando dependencias..."
Invoke-Native $UvBin @("pip", "install", "--python", $PythonBin, "-e", ".")

# Fail here, with a clear message, instead of as "Connection closed" inside Claude Code.
Write-Host "==> Verificando que Python puede cargar los MCP..."
& $PythonBin -c "import unicodedata, mcp_mysql.server, mcp_oracle.server, mcp_postgresql.server, mcp_sqlserver.server, mcp_informix.server"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    if (Test-SmartAppControlOn) {
        Write-Host "Smart App Control esta activo y es la causa mas probable: bloquea archivos .pyd de paquetes sin firma."
        Write-Host "Revisa el error de arriba. Si dice 'Una directiva de Control de aplicaciones bloqueo este archivo',"
        Write-Host "desactivalo en Seguridad de Windows > Control de aplicaciones y navegador > Configuracion de Smart App Control"
        Write-Host "(o pide a TI que lo haga) y vuelve a ejecutar este setup."
    }
    throw "Python no pudo cargar los MCP (ver el error de arriba)."
}

if (-not (Test-Path $EnvFile)) {
    Write-Host "==> No existe .env. Copiando .env.example -> .env"
    Copy-Item (Join-Path $RootDir ".env.example") $EnvFile
}

# Asks for the credentials of each chosen engine, writes them to .env and tests the connection.
if ($Selected.Count -gt 0) {
    Write-Host ""
    Write-Host "==> Datos de conexion de: $($Selected -join ' ')"
    & $PythonBin (Join-Path $ScriptDir "configure_env.py") @Selected
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
}

$ClaudeCommand = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$ClaudeLocal = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
$ClaudeBin = if ($ClaudeCommand) { $ClaudeCommand.Path } elseif (Test-Path $ClaudeLocal) { $ClaudeLocal } else { $null }

$Registered = New-Object System.Collections.Generic.List[string]
$Failed = New-Object System.Collections.Generic.List[string]
if ($Selected.Count -gt 0 -and $ClaudeBin) {
    Write-Host "==> Registrando los MCP en Claude Code (disponibles en todas tus carpetas)..."
    foreach ($Name in $Selected) {
        if (Register-Engine $Name) { $Registered.Add($Name) } else { $Failed.Add($Name) }
    }
}

$ConfiguredNow = @((Get-ConfiguredEngines) -split " " | Where-Object { $_ })
$Missing = @($Selected | Where-Object { $_ -notin $ConfiguredNow })

Write-Host ""
Write-Host "==> Entorno listo."
if ($Selected.Count -eq 0) {
    Write-Host "    - Completa en $EnvFile (quitando el # de cada linea) los datos de los motores que vayas a usar."
} elseif ($Missing.Count -gt 0) {
    Write-Host "    - Faltan los datos de conexion de: $($Missing -join ' '). Vuelve a ejecutar este setup para ingresarlos."
}
if ($Registered.Count -gt 0) {
    Write-Host "    - Abre Claude Code (si ya estaba abierto, reinicialo) y pide: `"prueba la conexion a $($Registered[0])`"."
} elseif ($Selected.Count -eq 0) {
    Write-Host "    - Registra cada MCP volviendo a ejecutar este setup, o desde una terminal (no dentro de Claude) con:"
    Write-Host "        claude mcp add --scope user <nombre> -- `"$PythonBin`" -m mcp_<nombre>"
    Write-Host "      (ej: claude mcp add --scope user mysql -- `"$PythonBin`" -m mcp_mysql)"
} elseif (-not $ClaudeBin) {
    Write-Host "    - No se encontro Claude Code (comando claude). Instalalo y vuelve a ejecutar este setup,"
    Write-Host "      o registra cada MCP desde una terminal (no dentro de Claude) con:"
    foreach ($Name in $Selected) {
        Write-Host "        claude mcp add --scope user $Name -- `"$PythonBin`" -m mcp_$Name"
    }
} else {
    Write-Host "    - Corrige lo indicado arriba y vuelve a ejecutar este setup."
}
Write-Host "    - Para cambiar credenciales mas adelante, vuelve a ejecutar este setup."
Write-Host "    - Para revisar el estado de los MCP: claude mcp list"

if ($Failed.Count -gt 0) {
    Write-Host ""
    Write-Host "ERROR: no se pudieron registrar: $($Failed -join ' ') (ver mensajes arriba)."
    exit 1
}
