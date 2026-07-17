[CmdletBinding()]
param(
    [string]$ServerUrl,
    [string]$PairingId,
    [string]$DisplayName = $env:COMPUTERNAME,
    [string]$PythonLauncher = "py",
    [switch]$ReplacePairing
)

$ErrorActionPreference = "Stop"
$TaskName = "Kasugai Homelab Agent"
$SourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is required. Run this installer as the Windows user who will own the agent."
}
$InstallRoot = Join-Path $env:LOCALAPPDATA "Kasugai\homelab-agent"
$AppRoot = Join-Path $InstallRoot "app"
$VenvRoot = Join-Path $InstallRoot "venv"
$DataRoot = Join-Path $InstallRoot "data"
$CredentialPath = Join-Path $DataRoot "credentials.json"
$ConfigPath = Join-Path $InstallRoot "config.json"
if ($ServerUrl -and -not $PairingId) {
    throw "PairingId is required when ServerUrl is supplied."
}
if ($PairingId -and -not $ServerUrl) {
    throw "ServerUrl is required when PairingId is supplied."
}

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $AppRoot) {
    $ResolvedInstall = [System.IO.Path]::GetFullPath($InstallRoot)
    $ExpectedParent = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Kasugai"))
    if (-not $ResolvedInstall.StartsWith($ExpectedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace an unexpected install path."
    }
    Remove-Item -LiteralPath $AppRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $AppRoot -Force | Out-Null
New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
$PackageRoot = Join-Path $AppRoot "homelab_agent"
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $SourceRoot "homelab_agent") -Filter "*.py" -File |
    Copy-Item -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $SourceRoot "requirements-homelab-agent.txt") -Destination $AppRoot

if (-not (Test-Path -LiteralPath (Join-Path $VenvRoot "Scripts\python.exe"))) {
    & $PythonLauncher -3 -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not create the homelab agent virtual environment."
    }
}
$AgentPython = Join-Path $VenvRoot "Scripts\python.exe"
& $AgentPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Kasugai homelab agent requires Python 3.10 or newer."
}
& $AgentPython -m pip install --disable-pip-version-check --requirement (Join-Path $AppRoot "requirements-homelab-agent.txt")
if ($LASTEXITCODE -ne 0) {
    throw "The homelab agent dependency installation failed."
}

Push-Location $AppRoot
try {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        & $AgentPython -m homelab_agent init-config --config $ConfigPath
        if ($LASTEXITCODE -ne 0) {
            throw "The disabled-by-default homelab policy could not be created."
        }
    }
    if ($ServerUrl) {
        $PairArguments = @(
            "-m", "homelab_agent", "pair",
            "--server", $ServerUrl,
            "--pairing-id", $PairingId,
            "--display-name", $DisplayName,
            "--config", $ConfigPath
        )
        if ($ReplacePairing -or (Test-Path -LiteralPath $CredentialPath)) {
            $PairArguments += "--replace"
        }
        & $AgentPython @PairArguments
        if ($LASTEXITCODE -ne 0) {
            throw "The homelab agent could not be paired."
        }
    }
    elseif (-not (Test-Path -LiteralPath $CredentialPath)) {
        throw "No existing pairing was found. Supply ServerUrl and PairingId from the dashboard."
    }
    else {
        & $AgentPython -m homelab_agent status --config $ConfigPath
        if ($LASTEXITCODE -ne 0) {
            throw "The preserved homelab pairing could not be opened by this Windows user."
        }
    }
}
finally {
    Pop-Location
}

$Action = New-ScheduledTaskAction `
    -Execute $AgentPython `
    -Argument "-m homelab_agent run --config `"$ConfigPath`"" `
    -WorkingDirectory $AppRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Outbound-only Kasugai Docker inventory, homelab health, and opt-in actions." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Kasugai homelab agent installed for the current Windows user."
Write-Host "Scheduled task: $TaskName"
Write-Host "Install path: $InstallRoot"
Write-Host "Local policy (all access disabled initially): $ConfigPath"
