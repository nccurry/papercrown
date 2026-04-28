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
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),
        "C:\msys64\ucrt64\bin"
    )
    $env:Path = (@($processPath, $userPath, $machinePath) + $extra |
        Where-Object { $_ } |
        ForEach-Object { $_.TrimEnd(";") }) -join ";"
}

function Get-VersionValue {
    param([string] $Name)

    $versionsPath = Join-Path $repoRoot "versions.env"
    if (-not (Test-Path $versionsPath)) {
        throw "versions.env is required but was not found."
    }
    foreach ($line in Get-Content -LiteralPath $versionsPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -eq 2 -and $parts[0].Trim() -eq $Name) {
            return $parts[1].Trim().Trim('"').Trim("'")
        }
    }
    throw "$Name is required in versions.env."
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

function Get-Sha256Hex {
    param([string] $Path)

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hash = [BitConverter]::ToString($sha256.ComputeHash($stream)) -replace "-", ""
            return $hash.ToLowerInvariant()
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
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

function Ensure-ObsidianExport {
    $version = Get-VersionValue -Name "OBSIDIAN_EXPORT_VERSION"
    $expected = "obsidian-export $version"
    $existing = Get-Command obsidian-export -ErrorAction SilentlyContinue
    if ($existing) {
        $actual = (& $existing.Source --version 2>$null | Select-Object -First 1)
        $source = $existing.Source.Replace("\", "/")
        if ($actual -eq $expected -and $source -notlike "*/.cargo/*") {
            return
        }
    }

    $binDir = Join-Path $HOME ".local\bin"
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    $asset = "obsidian-export-x86_64-pc-windows-msvc.zip"
    $baseUrl = "https://github.com/zoni/obsidian-export/releases/download/v$version"
    $zip = Join-Path $env:TEMP $asset
    $sha = "$zip.sha256"
    $extract = Join-Path $env:TEMP "obsidian-export-$version"
    if (Test-Path $extract) {
        Remove-Item -LiteralPath $extract -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $extract | Out-Null

    Write-Step "Installing obsidian-export $version"
    Invoke-WebRequest -Uri "$baseUrl/$asset" -OutFile $zip
    Invoke-WebRequest -Uri "$baseUrl/$asset.sha256" -OutFile $sha
    $expectedHash = ((Get-Content -LiteralPath $sha | Select-Object -First 1) -split "\s+")[0]
    $actualHash = Get-Sha256Hex -Path $zip
    if ($actualHash -ne $expectedHash.ToLowerInvariant()) {
        throw "obsidian-export checksum mismatch."
    }

    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $binary = Get-ChildItem -LiteralPath $extract -Recurse -Filter "obsidian-export.exe" |
        Select-Object -First 1
    if (-not $binary) {
        throw "obsidian-export.exe was not found in the release archive."
    }
    Copy-Item -LiteralPath $binary.FullName -Destination (Join-Path $binDir "obsidian-export.exe") -Force
    Add-UserPathEntry -Entry $binDir
    Refresh-Path
    $installed = Get-RequiredCommand "obsidian-export"
    $installedVersion = (& $installed --version 2>$null | Select-Object -First 1)
    if ($installedVersion -ne $expected) {
        throw "obsidian-export install produced '$installedVersion', expected '$expected'."
    }
}

function Ensure-NoRustInstallPath {
    if (Get-Command cargo -ErrorAction SilentlyContinue) {
        Write-Verbose "Cargo is installed locally, but Paper Crown does not require it."
        return
    }
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
Ensure-NoRustInstallPath
Ensure-ObsidianExport
Ensure-WindowsPdfRuntime

Write-Step "Syncing Python dependencies"
$uv = Get-RequiredCommand "uv"
& $uv sync --locked --all-groups

Write-Step "Verifying dependency state"
& $uv run --locked papercrown deps check
