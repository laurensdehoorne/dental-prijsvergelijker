# Installeert de Dentale Prijsvergelijker op Windows:
# Python-omgeving + snelkoppeling op bureaublad en in Startmenu.
# Starten via Installeer.bat (dubbelklikken).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "Dentale Prijsvergelijker installeren in $Root" -ForegroundColor Cyan

# 1. Python zoeken. 3.12 aanbevolen: pywebview heeft op Windows 'pythonnet' nodig,
#    en dat loopt vaak achter op de nieuwste Python-versie.
function Find-Python {
    foreach ($v in @("3.12", "3.13", "3.11")) {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch { }
    }
    $direct = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $direct) { return $direct }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.12 niet gevonden. Installeren via winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $python = Find-Python
    if (-not $python) {
        Write-Host "Python installeren lukte niet automatisch." -ForegroundColor Red
        Write-Host "Installeer Python 3.12 via https://www.python.org/downloads/ en start Installeer.bat opnieuw."
        exit 1
    }
}
Write-Host "Python: $python"

# 2. Python-omgeving met de benodigde pakketten
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $python -m venv .venv
}
& .venv\Scripts\python.exe -m pip install -q --upgrade pip
& .venv\Scripts\python.exe -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Pakketten installeren mislukt." -ForegroundColor Red; exit 1 }

# 3. Snelkoppelingen (pythonw = zonder zwart consolevenster)
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), $startMenu)) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "Prijsvergelijker.lnk"))
    $lnk.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
    $lnk.Arguments = '"' + (Join-Path $Root "desktop_app.py") + '"'
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = Join-Path $Root "assets\icon.ico"
    $lnk.Description = "Dentale Prijsvergelijker"
    $lnk.Save()
}

Write-Host ""
Write-Host "Klaar! Start 'Prijsvergelijker' via het bureaublad of het Startmenu." -ForegroundColor Green
Write-Host "Inloggen bij de winkels gebeurt in Chrome (of Edge als Chrome ontbreekt)."
