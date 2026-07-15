[CmdletBinding()]
param(
    [ValidateSet("combined", "dashboard-only")]
    [string]$Stack = "combined",

    [string]$LegacyConfig = $(
        if ($env:USERPROFILE) {
            Join-Path $env:USERPROFILE "Kasugai\config.ini"
        }
        else {
            ""
        }
    )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

if (-not $LegacyConfig) {
    throw "Pass -LegacyConfig with the path to the activated Kasugai config.ini."
}

$legacyItem = Get-Item -LiteralPath $LegacyConfig -ErrorAction Stop
if ($legacyItem.PSIsContainer) {
    throw "LegacyConfig must identify a config.ini file, not a directory."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeArguments = @("compose")
if ($Stack -eq "dashboard-only") {
    $composeArguments += @("-f", "docker-compose.dashboard.yml")
}

Push-Location $repositoryRoot
try {
    Invoke-Docker -Arguments ($composeArguments + @("build", "dashboard"))

    $containerIds = @(& docker @composeArguments ps --quiet dashboard)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the dashboard service."
    }

    $containerId = $containerIds | Select-Object -First 1
    $wasRunning = $false
    $publishedHost = ""
    if ($containerId) {
        $inspection = @(& docker inspect $containerId | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect the dashboard container."
        }
        $wasRunning = [bool]$inspection.State.Running
        $binding = $inspection.HostConfig.PortBindings.'8000/tcp' | Select-Object -First 1
        if ($binding) {
            $publishedHost = [string]$binding.HostIp
        }
    }

    if ($wasRunning) {
        Invoke-Docker -Arguments ($composeArguments + @("stop", "dashboard"))
    }

    try {
        $legacyTargetDirectory = "/run/kasugai-legacy"
        $legacyMount = "$($legacyItem.Directory.FullName):${legacyTargetDirectory}:ro"
        $legacyTarget = "$legacyTargetDirectory/$($legacyItem.Name)"
        Invoke-Docker -Arguments ($composeArguments + @(
            "run",
            "--rm",
            "--no-deps",
            "--volume", $legacyMount,
            "--env", "KASUGAI_LEGACY_CONFIG_FILE=$legacyTarget",
            "dashboard",
            "true"
        ))
    }
    finally {
        if ($wasRunning) {
            $hadBindHost = Test-Path Env:KASUGAI_DASHBOARD_BIND_HOST
            $previousBindHost = $env:KASUGAI_DASHBOARD_BIND_HOST
            try {
                if ($publishedHost) {
                    $env:KASUGAI_DASHBOARD_BIND_HOST = $publishedHost
                }
                Invoke-Docker -Arguments ($composeArguments + @(
                    "up", "-d", "--wait", "--no-deps", "dashboard"
                ))
            }
            finally {
                if ($hadBindHost) {
                    $env:KASUGAI_DASHBOARD_BIND_HOST = $previousBindHost
                }
                else {
                    Remove-Item Env:KASUGAI_DASHBOARD_BIND_HOST -ErrorAction SilentlyContinue
                }
            }
        }
    }

    Write-Host "Docker now uses the existing DeniLicense activation identity."
    if (-not $wasRunning) {
        Write-Host "Start the dashboard normally with Docker Compose."
    }
}
finally {
    Pop-Location
}
