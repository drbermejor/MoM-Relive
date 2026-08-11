param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir
$Version = (python -c "from version import __version__; print(__version__)").Trim()
if (-not $Version) { throw "Could not read the version" }

if (-not $SkipTests) {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name MoMRevival mom_revival.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name MoMClientLauncher client_launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed while building the launcher" }

python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name MoMServerManager server_manager.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed while building the server manager" }

python -m PyInstaller --noconfirm --clean --onefile --console --uac-admin `
    --name MoMNativeServer native_server.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed while building the native server launcher" }

$Exe = Join-Path $ProjectDir "dist\MoMRevival.exe"
if (-not (Test-Path -LiteralPath $Exe)) { throw "$Exe was not generated" }
$LauncherExe = Join-Path $ProjectDir "dist\MoMClientLauncher.exe"
if (-not (Test-Path -LiteralPath $LauncherExe)) { throw "$LauncherExe was not generated" }
$ManagerExe = Join-Path $ProjectDir "dist\MoMServerManager.exe"
if (-not (Test-Path -LiteralPath $ManagerExe)) { throw "$ManagerExe was not generated" }
$NativeServerExe = Join-Path $ProjectDir "dist\MoMNativeServer.exe"
if (-not (Test-Path -LiteralPath $NativeServerExe)) { throw "$NativeServerExe was not generated" }

$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 was not found (winget install JRSoftware.InnoSetup)"
}
& $Iscc "/DMyAppVersion=$Version" (Join-Path $ProjectDir "installer\MoMRevival.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$Installer = Join-Path $ProjectDir "dist\MoMRevivalSetup.exe"
if (-not (Test-Path -LiteralPath $Installer)) { throw "$Installer was not generated" }
$LegacyInstaller = Join-Path $ProjectDir "dist\MoMRevivalInstaller.exe"
if (Test-Path -LiteralPath $LegacyInstaller -PathType Leaf) {
    Remove-Item -LiteralPath $LegacyInstaller -Force
}
Write-Host "Client: $Exe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $Exe).Hash)"
Write-Host "Launcher: $LauncherExe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $LauncherExe).Hash)"
Write-Host "Server manager: $ManagerExe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $ManagerExe).Hash)"
Write-Host "Native server: $NativeServerExe"
Write-Host "  SHA256:  $((Get-FileHash -Algorithm SHA256 -LiteralPath $NativeServerExe).Hash)"
Write-Host "Installer: $Installer"
Write-Host "  SHA256:   $((Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash)"
