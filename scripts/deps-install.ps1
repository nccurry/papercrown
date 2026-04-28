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
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),
        "C:\msys64\ucrt64\bin"
    )
    $env:Path = (@($processPath, $userPath, $machinePath) + $extra |
        Where-Object { $_ } |
        ForEach-Object { $_.TrimEnd(";") }) -join ";"
}

function Add-UserPathEntry {
    param([string] $Entry)

    $normalizedEntry = $Entry.TrimEnd("\")
    $processEntries = @($env:Path -split ";" | Where-Object { $_ })
    if (-not ($processEntries | Where-Object { $_.TrimEnd("\") -ieq $normalizedEntry })) {
        $env:Path = "$Entry;$env:Path"
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $userEntries = @($userPath -split ";" | Where-Object { $_ })
    if (-not ($userEntries | Where-Object { $_.TrimEnd("\") -ieq $normalizedEntry })) {
        [Environment]::SetEnvironmentVariable("Path", (($userEntries + $Entry) -join ";"), "User")
    }
}

function Get-RequiredCommand {
    param([string] $Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name is required but was not found on PATH."
    }
    return $command.Source
}

function Get-Winget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget is required for automatic Windows dependency installation."
    }
    return $winget.Source
}

function Install-WingetPackage {
    param(
        [string] $Id,
        [string] $Name
    )
    $winget = Get-Winget
    Write-Step "Installing $Name with winget"
    & $winget install --id $Id -e --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        return
    }

    Write-Step "Installing uv"
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
    Get-RequiredCommand "uv" | Out-Null
}

function Ensure-Pandoc {
    if (Get-Command pandoc -ErrorAction SilentlyContinue) {
        return
    }
    Install-WingetPackage -Id "JohnMacFarlane.Pandoc" -Name "Pandoc"
    Get-RequiredCommand "pandoc" | Out-Null
}

function Ensure-Rust {
    if (Get-Command cargo -ErrorAction SilentlyContinue) {
        return
    }
    Install-WingetPackage -Id "Rustlang.Rustup" -Name "Rustup"
    Refresh-Path
    Get-RequiredCommand "cargo" | Out-Null
}

function Ensure-ObsidianExport {
    if (Get-Command obsidian-export -ErrorAction SilentlyContinue) {
        return
    }
    Ensure-Rust
    Write-Step "Installing obsidian-export"
    $cargo = Get-RequiredCommand "cargo"
    & $cargo install obsidian-export --locked
    Refresh-Path
    Get-RequiredCommand "obsidian-export" | Out-Null
}

function Ensure-WindowsPdfRuntime {
    $msysBash = "C:\msys64\usr\bin\bash.exe"
    $msysBin = "C:\msys64\ucrt64\bin"
    $pangoDll = Join-Path $msysBin "libpango-1.0-0.dll"

    if (-not (Test-Path $pangoDll)) {
        if (-not (Test-Path $msysBash)) {
            Install-WingetPackage -Id "MSYS2.MSYS2" -Name "MSYS2"
        }
        if (-not (Test-Path $msysBash)) {
            throw "MSYS2 was installed but $msysBash was not found."
        }

        Write-Step "Installing MSYS2 UCRT64 Pango/GLib runtime"
        & $msysBash -lc "pacman -Syu --noconfirm"
        & $msysBash -lc "pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-pango"
    }

    $env:WEASYPRINT_DLL_DIRECTORIES = $msysBin
    [Environment]::SetEnvironmentVariable("WEASYPRINT_DLL_DIRECTORIES", $env:WEASYPRINT_DLL_DIRECTORIES, "User")
    Add-UserPathEntry -Entry $msysBin
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
Refresh-Path

Ensure-Uv
Ensure-Pandoc
Ensure-Rust
Ensure-ObsidianExport
Ensure-WindowsPdfRuntime

Write-Step "Syncing Python dependencies"
$uv = Get-RequiredCommand "uv"
& $uv sync --locked --all-groups

Write-Step "Verifying dependency state"
& $uv run --locked papercrown deps check
