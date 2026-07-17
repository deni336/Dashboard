[CmdletBinding()]
param(
    [switch]$RemoveCredentials
)

$ErrorActionPreference = "Stop"
$TaskName = "Kasugai Workstation Agent"
if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is required."
}
$InstallRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Kasugai\workstation-agent"))
$ExpectedParent = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Kasugai"))
if (-not $InstallRoot.StartsWith($ExpectedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove an unexpected install path."
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

foreach ($Child in @("app", "venv", "agent.log", "agent.log.1", "agent.log.2")) {
    $Target = Join-Path $InstallRoot $Child
    if (Test-Path -LiteralPath $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
    }
}
if ($RemoveCredentials) {
    $DataPath = Join-Path $InstallRoot "data"
    if (Test-Path -LiteralPath $DataPath) {
        Remove-Item -LiteralPath $DataPath -Recurse -Force
    }
}
if ((Test-Path -LiteralPath $InstallRoot) -and -not (Get-ChildItem -LiteralPath $InstallRoot -Force)) {
    Remove-Item -LiteralPath $InstallRoot -Force
}

Write-Host "Kasugai workstation agent removed."
if (-not $RemoveCredentials) {
    Write-Host "The DPAPI-protected pairing was preserved. Use -RemoveCredentials to delete it."
}
