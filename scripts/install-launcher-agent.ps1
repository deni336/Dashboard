[CmdletBinding()]
param(
    [string]$ServerUrl,
    [string]$PairingId,
    [string]$DisplayName = $env:COMPUTERNAME,
    [string]$PythonLauncher = "py",
    [switch]$ReplacePairing
)

$ErrorActionPreference = "Stop"
$TaskName = "Kasugai Launcher Agent"
$SourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is required. Run this installer as the Windows user who will own the runner."
}
$InstallRoot = Join-Path $env:LOCALAPPDATA "Kasugai\launcher-agent"
$AppRoot = Join-Path $InstallRoot "app"
$VenvRoot = Join-Path $InstallRoot "venv"
$CredentialPath = Join-Path $InstallRoot "data\credentials.json"
$PolicyPath = Join-Path $InstallRoot "policy.json"
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
$PackageRoot = Join-Path $AppRoot "launcher_agent"
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $SourceRoot "launcher_agent") -File |
    Copy-Item -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $SourceRoot "requirements-launcher-agent.txt") -Destination $AppRoot

if (-not (Test-Path -LiteralPath (Join-Path $VenvRoot "Scripts\python.exe"))) {
    & $PythonLauncher -3 -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not create the launcher agent virtual environment."
    }
}
$AgentPython = Join-Path $VenvRoot "Scripts\python.exe"
& $AgentPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Kasugai launcher agent requires Python 3.10 or newer."
}
& $AgentPython -m pip install --disable-pip-version-check --requirement (Join-Path $AppRoot "requirements-launcher-agent.txt")
if ($LASTEXITCODE -ne 0) {
    throw "The launcher agent dependency installation failed."
}

Push-Location $AppRoot
try {
    if (-not (Test-Path -LiteralPath $PolicyPath)) {
        & $AgentPython -m launcher_agent config init
        if ($LASTEXITCODE -ne 0) {
            throw "The disabled launcher policy could not be initialized."
        }
    }
    else {
        & $AgentPython -m launcher_agent config validate
        if ($LASTEXITCODE -ne 0) {
            throw "The existing launcher policy is invalid."
        }
    }

    if ($ServerUrl) {
        $PairArguments = @(
            "-m", "launcher_agent", "pair",
            "--server", $ServerUrl,
            "--pairing-id", $PairingId,
            "--display-name", $DisplayName
        )
        if ($ReplacePairing -or (Test-Path -LiteralPath $CredentialPath)) {
            $PairArguments += "--replace"
        }
        & $AgentPython @PairArguments
        if ($LASTEXITCODE -ne 0) {
            throw "The launcher agent could not be paired."
        }
    }
    elseif (-not (Test-Path -LiteralPath $CredentialPath)) {
        throw "No existing pairing was found. Supply ServerUrl and PairingId from the dashboard."
    }
    else {
        & $AgentPython -m launcher_agent status
        if ($LASTEXITCODE -ne 0) {
            throw "The preserved launcher pairing could not be opened by this Windows user."
        }
    }
}
finally {
    Pop-Location
}

$Action = New-ScheduledTaskAction `
    -Execute $AgentPython `
    -Argument "-m launcher_agent run" `
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
    -Description "Outbound-only Kasugai runner for tasks approved in a local policy file." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Kasugai launcher agent installed for the current Windows user."
Write-Host "Scheduled task: $TaskName"
Write-Host "Install path: $InstallRoot"
Write-Host "Local policy (disabled by default): $PolicyPath"
