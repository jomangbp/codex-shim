<#
.SYNOPSIS
  Install codex-profile-switcher for Windows 11 / WSL
#>
param(
  [string]$InstallDir = "$env:USERPROFILE\.local\bin"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Codex Profile Switcher - Windows Installer ===" -ForegroundColor Cyan

# Detect WSL
$IsWSL = $false
if (Test-Path "/proc/version") {
  $IsWSL = $true
  $InstallDir = "$env:HOME/.local/bin"
  Write-Host "Detected WSL environment." -ForegroundColor Yellow
}

# Create install directory
if (-not (Test-Path $InstallDir)) {
  New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# Copy the PowerShell script
$source = Join-Path $PSScriptRoot "codex-profile-switcher.ps1"
$dest = Join-Path $InstallDir "codex-profile-switcher.ps1"
Copy-Item -Path $source -Destination $dest -Force
Write-Host "Installed: $dest" -ForegroundColor Green

# Create a batch launcher for easy invocation from cmd
$batchContent = "@echo off`r`n" + 'powershell -ExecutionPolicy Bypass -File "' + $dest + '" %*' + "`r`n"
$batchPath = Join-Path $InstallDir "codex-profile-switcher.bat"
Set-Content -Path $batchPath -Value $batchContent
Write-Host "Installed: $batchPath" -ForegroundColor Green

# Create a desktop shortcut for the GUI
if (-not $IsWSL) {
  $desktopPath = [Environment]::GetFolderPath("Desktop")
  $shortcutPath = Join-Path $desktopPath "Codex Profile Switcher.lnk"
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = "powershell.exe"
  $shortcut.Arguments = '-ExecutionPolicy Bypass -File "' + $dest + '" gui'
  $shortcut.IconLocation = "shell32.dll,13"
  $shortcut.Description = "Codex Profile Switcher - switch between shim and default profiles"
  $shortcut.Save()
  Write-Host "Desktop shortcut created: $shortcutPath" -ForegroundColor Green
}

# Add to PATH if not already there
$pathDirs = $env:PATH -split ";"
if ($InstallDir -notin $pathDirs) {
  Write-Host "`nTo add to PATH, run:" -ForegroundColor Yellow
  Write-Host "  [Environment]::SetEnvironmentVariable('PATH', `$env:PATH + ';$InstallDir', 'User')" -ForegroundColor DarkYellow
}

# Ensure .codex directory exists
$codexDir = if ($IsWSL) { "$env:HOME/.codex" } else { "$env:USERPROFILE\.codex" }
if (-not (Test-Path $codexDir)) {
  New-Item -ItemType Directory -Path $codexDir -Force | Out-Null
  Write-Host "Created: $codexDir" -ForegroundColor Green
}

# Ensure .codex-shim directory exists
$shimConfigDir = if ($IsWSL) { "$env:HOME/.codex-shim" } else { "$env:USERPROFILE\.codex-shim" }
if (-not (Test-Path $shimConfigDir)) {
  New-Item -ItemType Directory -Path $shimConfigDir -Force | Out-Null
  Write-Host "Created: $shimConfigDir" -ForegroundColor Green
}

Write-Host "`n=== Installation complete ===" -ForegroundColor Cyan
Write-Host "Run 'codex-profile-switcher gui' to open the GUI." -ForegroundColor White
Write-Host "Run 'codex-profile-switcher models' to list available models." -ForegroundColor White
Write-Host "Run 'codex-profile-switcher help' for full usage." -ForegroundColor White
