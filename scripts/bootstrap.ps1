[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string] $Message)
    Write-Host "==> $Message"
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    $extra = @(
        (Join-Path $HOME ".local\bin"),
        (Join-Path $HOME ".cargo\bin"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps")
    )
    $env:Path = (@($processPath, $userPath, $machinePath) + $extra |
        Where-Object { $_ } |
        ForEach-Object { $_.TrimEnd(";") }) -join ";"
}

function Find-TaskPath {
    $command = Get-Command task -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"),
        (Join-Path $env:LOCALAPPDATA "Programs")
    ) | Where-Object { Test-Path $_ }

    foreach ($root in $roots) {
        $candidate = Get-ChildItem -LiteralPath $root -Recurse -Filter task.exe -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($candidate) {
            $env:Path = "$($candidate.Directory.FullName);$env:Path"
            return $candidate.FullName
        }
    }

    return $null
}

function Ensure-Task {
    Refresh-Path
    $taskPath = Find-TaskPath
    if ($taskPath) {
        return $taskPath
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Task is not installed and winget is not available. Install Task, then run: task deps:install"
    }

    Write-Step "Installing Task with winget"
    & $winget.Source install --id Task.Task -e --accept-package-agreements --accept-source-agreements
    Refresh-Path

    $taskPath = Find-TaskPath
    if (-not $taskPath) {
        throw "Task was installed but was not found in this session. Open a new terminal, then run: task deps:install"
    }

    return $taskPath
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$task = Ensure-Task
Write-Step "Installing Paper Crown dependencies through Task"
& $task deps:install
