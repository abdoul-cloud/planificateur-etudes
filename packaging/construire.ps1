# Construit l'installateur Windows de A à Z.
#   powershell -ExecutionPolicy Bypass -File packaging\construire.ps1
# Étapes : tests -> application autonome (PyInstaller) -> auto-test de l'exécutable -> setup.exe (Inno Setup)

$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $PSScriptRoot
Set-Location $racine
$python = Join-Path $racine ".venv\Scripts\python.exe"

Write-Host "1/4  Tests..." -ForegroundColor Cyan
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Les tests échouent : construction annulée." }

Write-Host "2/4  Application autonome (PyInstaller)..." -ForegroundColor Cyan
& $python -m PyInstaller packaging\planificateur.spec --noconfirm --distpath build\dist --workpath build\work --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué." }

Write-Host "3/4  Auto-test de l'exécutable..." -ForegroundColor Cyan
$exe = Join-Path $racine "build\dist\PlanificateurEtudes\PlanificateurEtudes.exe"
$test = Start-Process -FilePath $exe -ArgumentList "--autotest" -Wait -PassThru
if ($test.ExitCode -ne 0) { throw "L'exécutable construit ne passe pas son auto-test (voir %TEMP%\planificateur-autotest-*)." }

Write-Host "4/4  Programme d'installation (Inno Setup)..." -ForegroundColor Cyan
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 est introuvable (winget install JRSoftware.InnoSetup)." }
& $iscc /Q packaging\installateur.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a échoué." }

$sortie = Get-ChildItem build\installateur\*.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ("Terminé : {0} ({1:N1} Mo)" -f $sortie.FullName, ($sortie.Length / 1MB)) -ForegroundColor Green
