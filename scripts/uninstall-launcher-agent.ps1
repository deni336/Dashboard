[CmdletBinding()]
param(
    [switch]$RemoveCredentials,
    [switch]$RemovePolicy
)

$ErrorActionPreference = "Stop"
$TaskName = "Kasugai Launcher Agent"
if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is required."
}
$InstallRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Kasugai\launcher-agent"))
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
if ($RemovePolicy) {
    $PolicyPath = Join-Path $InstallRoot "policy.json"
    if (Test-Path -LiteralPath $PolicyPath) {
        Remove-Item -LiteralPath $PolicyPath -Force
    }
}
if ((Test-Path -LiteralPath $InstallRoot) -and -not (Get-ChildItem -LiteralPath $InstallRoot -Force)) {
    Remove-Item -LiteralPath $InstallRoot -Force
}

Write-Host "Kasugai launcher agent removed."
if (-not $RemoveCredentials) {
    Write-Host "The DPAPI-protected pairing was preserved. Use -RemoveCredentials to delete it."
}
if (-not $RemovePolicy) {
    Write-Host "The local task policy was preserved. Use -RemovePolicy to delete it."
}
