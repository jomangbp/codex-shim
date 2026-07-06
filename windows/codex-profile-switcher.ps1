<#
.SYNOPSIS
  Codex Profile Switcher for Windows 11 / WSL
  Mirrors the Mac version: switch between default and shim profiles,
  select models, restart Codex.

.DESCRIPTION
  Usage:
    codex-profile-switcher.ps1 status
    codex-profile-switcher.ps1 default [-Restart]
    codex-profile-switcher.ps1 shim [-Restart]
    codex-profile-switcher.ps1 toggle [-Restart]
    codex-profile-switcher.ps1 models [-Menu]
    codex-profile-switcher.ps1 model <slug>
    codex-profile-switcher.ps1 gui

  The "gui" command opens a WinForms dialog matching the Mac AppleScript UI.
#>

param(
  [Parameter(Position = 0)]
  [string]$Command = "help",

  [Parameter(Position = 1, ValueFromRemainingArguments)]
  [string[]]$RestArgs,

  [switch]$Restart,
  [switch]$Menu
)

# --- Configuration -----------------------------------------------------------

$HOME_DIR = $env:USERPROFILE
if (-not $HOME_DIR) { $HOME_DIR = "$env:HOMEDRIVE$env:HOMEPATH" }

# When running inside WSL, $HOME is different — detect and adapt
$IsWSL = $false
if (Test-Path "/proc/version") {
  $IsWSL = $true
  $HOME_DIR = $env:HOME
}

$CODEX_DIR = Join-Path $HOME_DIR ".codex"
$CONFIG = Join-Path $CODEX_DIR "config.toml"
$DEFAULT_TEMPLATE = Join-Path $CODEX_DIR "default.config.toml"
$SHIM_TEMPLATE = Join-Path $CODEX_DIR "shim.config.toml"
$BACKUP_DIR = Join-Path $CODEX_DIR "profile-switcher-backups"

# Shim paths — in WSL these are Linux paths, in native Windows use forward slashes
if ($IsWSL) {
  $SHIM_REPO = "$HOME_DIR/.local/src/codex-shim"
  $SHIM_CATALOG = "$SHIM_REPO/.codex-shim/custom_model_catalog.json"
} else {
  $SHIM_REPO = Join-Path $HOME_DIR ".local\src\codex-shim"
  $SHIM_CATALOG = Join-Path $SHIM_REPO ".codex-shim\custom_model_catalog.json"
}

$SHIM_PROVIDER = "codex_shim"
$SHIM_BASE_URL = "http://127.0.0.1:8765/v1"

$MANAGED_BEGIN = "# >>> codex-profile-switcher managed >>>"
$MANAGED_END = "# <<< codex-profile-switcher managed <<<"
$CODEX_SHIM_BEGIN = "# >>> codex-shim managed >>>"
$CODEX_SHIM_END = "# <<< codex-shim managed <<<"

# --- Helpers ----------------------------------------------------------------

function Die([string]$Msg, [int]$Code = 1) {
  Write-Error $Msg
  exit $Code
}

function Read-Config {
  if (-not (Test-Path $CONFIG)) { return "" }
  return Get-Content $CONFIG -Raw
}

function Backup-Config([string]$Text) {
  if (-not (Test-Path $BACKUP_DIR)) {
    New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null
  }
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $path = Join-Path $BACKUP_DIR "config.toml.$stamp.bak"
  Set-Content -Path $path -Value $Text -NoNewline
  return $path
}

function Remove-MarkedBlocks([string]$Text, [string]$Begin, [string]$End) {
  while ($Text.Contains($Begin)) {
    $idx = $Text.IndexOf($Begin)
    $endIdx = $Text.IndexOf($End, $idx)
    if ($endIdx -lt 0) {
      $Text = $Text.Substring(0, $idx).TrimEnd() + "`n"
      break
    }
    $Text = $Text.Substring(0, $idx) + $Text.Substring($endIdx + $End.Length)
  }
  return $Text
}

function Remove-Section([string]$Text, [string]$Section) {
  $header = "[$Section]"
  $lines = $Text -split "`n"
  $out = @()
  $skipping = $false
  foreach ($line in $lines) {
    if ($line.Trim() -eq $header) { $skipping = $true; continue }
    if ($skipping -and $line.TrimStart().StartsWith("[") -and $line.Trim() -ne $header) {
      $skipping = $false
    }
    if (-not $skipping) { $out += $line }
  }
  return ($out -join "`n")
}

function Get-CurrentProfile([string]$Text) {
  $managedMatch = [regex]::Match($Text, "(?s)" + [regex]::Escape($MANAGED_BEGIN) + "(.*?)" + [regex]::Escape($MANAGED_END))
  if ($managedMatch.Success) {
    $block = $managedMatch.Groups[1].Value
    if ($block -match 'profile\s*=\s*"shim"') { return "shim" }
    if ($block -match 'profile\s*=\s*"default"') { return "default" }
  }
  if ($Text -match 'model_provider\s*=\s*"(codex_shim|factory_byok_shim)"') { return "shim" }
  return "default"
}

function Get-CurrentModel {
  $text = Read-Config
  if ($text -match 'model\s*=\s*"([^"]+)"') { return $Matches[1] }
  return ""
}

function Get-ShimModel([string]$Text) {
  if ($Text -match 'model\s*=\s*"([^"]+)"') { return $Matches[1] }
  return $null
}

function Ensure-ShimStarted {
  # Check if shim is running on port 8765
  try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 3 -ErrorAction Stop
    if ($response) { return }
  } catch {}

  # Start the shim
  $shimModule = Join-Path $SHIM_REPO "codex_shim"
  if (-not (Test-Path $shimModule)) {
    Write-Host "Shim not found at $SHIM_REPO. Clone codex-shim first." -ForegroundColor Yellow
    return
  }

  if ($IsWSL) {
    $settingsPath = "$HOME_DIR/.codex-shim/models.json"
    Start-Process -NoNewWindow -FilePath "python3" -ArgumentList "-m", "codex_shim.server", "--settings", $settingsPath, "--host", "127.0.0.1", "--port", "8765" -WorkingDirectory $SHIM_REPO
  } else {
    $settingsPath = Join-Path $HOME_DIR ".codex-shim\models.json"
    $venvPython = Join-Path $SHIM_REPO ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
      Start-Process -NoNewWindow -FilePath $venvPython -ArgumentList "-m", "codex_shim.server", "--settings", $settingsPath, "--host", "127.0.0.1", "--port", "8765" -WorkingDirectory $SHIM_REPO
    } else {
      Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m", "codex_shim.server", "--settings", $settingsPath, "--host", "127.0.0.1", "--port", "8765" -WorkingDirectory $SHIM_REPO
    }
  }

  # Wait for it to be ready
  for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    try {
      $null = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2 -ErrorAction Stop
      Write-Host "Shim started." -ForegroundColor Green
      return
    } catch {}
  }
  Write-Host "Shim failed to start within 15s." -ForegroundColor Yellow
}

function Restart-Codex {
  # Try to quit Codex gracefully
  if ($IsWSL) {
    # WSL: Codex runs in the terminal, not as a GUI app
    Write-Host "In WSL, restart Codex by closing and reopening your terminal session."
    return
  }

  # Windows native: look for Codex process
  $codexProc = Get-Process -Name "Codex" -ErrorAction SilentlyContinue
  if ($codexProc) {
    Write-Host "Quitting Codex..." -ForegroundColor Cyan
    $codexProc | Stop-Process -Force
    Start-Sleep -Seconds 2
  }

  # Restart Codex
  $codexPaths = @(
    Join-Path $env:LOCALAPPDATA "Programs\Codex\Codex.exe",
    Join-Path $env:PROGRAMFILES "Codex\Codex.exe",
    Join-Path $HOME_DIR "AppData\Local\Programs\Codex\Codex.exe"
  )

  foreach ($path in $codexPaths) {
    if (Test-Path $path) {
      Write-Host "Starting Codex from $path" -ForegroundColor Green
      Start-Process -FilePath $path
      return
    }
  }
  Write-Host "Codex executable not found. Start it manually." -ForegroundColor Yellow
}

function Ensure-Templates {
  $defaultContent = @"
# Codex default profile — uses OpenAI ChatGPT subscription
model = "gpt-5.5"
model_provider = "openai"

[model_providers.openai]
name = "OpenAI"
"@

  $shimContent = @"
# >>> codex-shim managed >>>
model = "kimi-k2-7-code-cloud"
model_provider = "codex_shim"
model_catalog_json = "$SHIM_CATALOG"

[model_providers.codex_shim]
name = "Codex Shim"
base_url = "$SHIM_BASE_URL"
wire_api = "responses"
experimental_bearer_token = "dummy"
request_max_retries = 3
stream_max_retries = 3
stream_idle_timeout_ms = 600000
# <<< codex-shim managed <<<
"@

  if (-not (Test-Path $DEFAULT_TEMPLATE)) {
    Set-Content -Path $DEFAULT_TEMPLATE -Value $defaultContent
  }
  if (-not (Test-Path $SHIM_TEMPLATE)) {
    Set-Content -Path $SHIM_TEMPLATE -Value $shimContent
  }
}

function Write-Model([string]$Slug) {
  $text = Read-Config
  $backup = Backup-Config $text

  # Remove existing model and provider lines
  $text = $text -replace '(?m)^model\s*=\s*"[^"]*"\s*\r?\n', ""
  $text = $text -replace '(?m)^model_provider\s*=\s*"[^"]*"\s*\r?\n', ""
  $text = $text -replace '(?m)^model_catalog_json\s*=\s*"[^"]*"\s*\r?\n', ""

  # Add new model lines
  $modelBlock = @"
model = "$Slug"
model_provider = "$SHIM_PROVIDER"
model_catalog_json = "$SHIM_CATALOG"
"@

  # Remove old shim managed block and inject new one
  $text = Remove-MarkedBlocks $text $CODEX_SHIM_BEGIN $CODEX_SHIM_END

  $providerBlock = @"
$CODEX_SHIM_BEGIN
[model_providers.$SHIM_PROVIDER]
name = "Codex Shim"
base_url = "$SHIM_BASE_URL"
wire_api = "responses"
experimental_bearer_token = "dummy"
request_max_retries = 3
stream_max_retries = 3
stream_idle_timeout_ms = 600000
$CODEX_SHIM_END
"@

  $text = $modelBlock + "`n`n" + $text.TrimStart() + "`n`n" + $providerBlock + "`n"
  Set-Content -Path $CONFIG -Value $text -NoNewline
  Write-Host "Shim model set to: $Slug" -ForegroundColor Green
  Write-Host "(applied to active config.toml)" -ForegroundColor DarkGray
}

function Load-Models {
  if (-not (Test-Path $SHIM_CATALOG)) {
    # Try fetching from the shim API
    try {
      $response = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/models" -TimeoutSec 5 -ErrorAction Stop
      return $response | ForEach-Object { @{ slug = $_.slug; display_name = $_.display_name } }
    } catch {
      Write-Error "No model catalog found. Run codex-shim generate first."
      exit 1
    }
  }

  $data = Get-Content $SHIM_CATALOG -Raw | ConvertFrom-Json
  return $data.models | ForEach-Object { @{ slug = $_.slug; display_name = $_.display_name } }
}

function List-Models([bool]$AsMenu) {
  $active = Get-CurrentModel
  $models = Load-Models

  if ($AsMenu) {
    foreach ($m in $models) {
      $suffix = if ($m.slug -eq $active) { " [active]" } else { "" }
      Write-Host "$($m.slug) | $($m.display_name)$suffix"
    }
    return
  }

  $width = ($models | ForEach-Object { $_.slug.Length } | Measure-Object -Maximum).Maximum
  foreach ($m in $models) {
    $marker = if ($m.slug -eq $active) { " *" } else { "  " }
    $slugPadded = $m.slug.PadRight($width)
    Write-Host "$marker $slugPadded  $($m.display_name)"
  }
}

function Switch-Profile([string]$Profile, [bool]$DoRestart) {
  Ensure-Templates
  $text = Read-Config
  $backupPath = Backup-Config $text

  if ($Profile -eq "shim") {
    Ensure-ShimStarted
    # Read shim template and inject
    $shimText = Get-Content $SHIM_TEMPLATE -Raw
    $model = Get-ShimModel $shimText
    if ($model) {
      Write-Model $model
    } else {
      # Just inject the provider block
      $text = Remove-MarkedBlocks $text $CODEX_SHIM_BEGIN $CODEX_SHIM_END
      $text = Remove-Section $text "model_providers.$SHIM_PROVIDER"
      $text = $text -replace '(?m)^model_provider\s*=.*$', "model_provider = `"$SHIM_PROVIDER`""
      Set-Content -Path $CONFIG -Value $text -NoNewline
    }
    Write-Host "Switched to shim profile." -ForegroundColor Green
  } elseif ($Profile -eq "default") {
    $defaultText = Get-Content $DEFAULT_TEMPLATE -Raw
    $text = Remove-MarkedBlocks $text $CODEX_SHIM_BEGIN $CODEX_SHIM_END
    $text = Remove-Section $text "model_providers.$SHIM_PROVIDER"
    $text = $text -replace '(?m)^model_provider\s*=.*$', ""
    $text = $defaultText + "`n" + $text
    Set-Content -Path $CONFIG -Value $text -NoNewline
    Write-Host "Switched to default profile." -ForegroundColor Green
  }

  Write-Host "Backup saved to: $backupPath" -ForegroundColor DarkGray

  if ($DoRestart) {
    Restart-Codex
  }
}

# --- GUI (WinForms) ---------------------------------------------------------

function Show-Gui {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing

  $form = New-Object System.Windows.Forms.Form
  $form.Text = "Codex Profile Switcher"
  $form.Size = New-Object System.Drawing.Size(500, 480)
  $form.StartPosition = "CenterScreen"
  $form.FormBorderStyle = "FixedDialog"
  $form.MaximizeBox = $false

  # Status label
  $statusLabel = New-Object System.Windows.Forms.Label
  $statusLabel.Location = New-Object System.Drawing.Point(20, 15)
  $statusLabel.Size = New-Object System.Drawing.Size(440, 30)
  $currentProfile = Get-CurrentProfile (Read-Config)
  $currentModel = Get-CurrentModel
  $statusLabel.Text = "Current: $currentProfile | Model: $currentModel"
  $statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
  $form.Controls.Add($statusLabel)

  # Model listbox
  $modelLabel = New-Object System.Windows.Forms.Label
  $modelLabel.Location = New-Object System.Drawing.Point(20, 50)
  $modelLabel.Size = New-Object System.Drawing.Size(200, 20)
  $modelLabel.Text = "Select Shim Model:"
  $form.Controls.Add($modelLabel)

  $listBox = New-Object System.Windows.Forms.ListBox
  $listBox.Location = New-Object System.Drawing.Point(20, 75)
  $listBox.Size = New-Object System.Drawing.Size(340, 200)
  $listBox.Font = New-Object System.Drawing.Font("Consolas", 9)

  $models = Load-Models
  $active = Get-CurrentModel
  foreach ($m in $models) {
    $suffix = if ($m.slug -eq $active) { " *" } else { "" }
    $listBox.Items.Add("$($m.display_name)$suffix") | Out-Null
  }
  # Store slugs in a parallel array
  $script:modelSlugs = $models | ForEach-Object { $_.slug }
  $form.Controls.Add($listBox)

  # Buttons
  $btnSetModel = New-Object System.Windows.Forms.Button
  $btnSetModel.Location = New-Object System.Drawing.Point(370, 75)
  $btnSetModel.Size = New-Object System.Drawing.Size(100, 30)
  $btnSetModel.Text = "Set Model"
  $btnSetModel.Add_Click({
    if ($listBox.SelectedIndex -ge 0) {
      $slug = $script:modelSlugs[$listBox.SelectedIndex]
      Write-Model $slug
      $statusLabel.Text = "Current: shim | Model: $slug"
      [System.Windows.Forms.MessageBox]::Show("Model set to: $slug`n`nSwitch to shim profile now?", "Model Selected", [System.Windows.Forms.MessageBoxButtons]::YesNo) | ForEach-Object {
        if ($_ -eq [System.Windows.Forms.DialogResult]::Yes) {
          Switch-Profile "shim" $false
        }
      }
    }
  })
  $form.Controls.Add($btnSetModel)

  $btnShim = New-Object System.Windows.Forms.Button
  $btnShim.Location = New-Object System.Drawing.Point(20, 300)
  $btnShim.Size = New-Object System.Drawing.Size(140, 35)
  $btnShim.Text = "Switch to Shim"
  $btnShim.Add_Click({
    Switch-Profile "shim" $false
    $statusLabel.Text = "Current: shim | Model: $(Get-CurrentModel)"
  })
  $form.Controls.Add($btnShim)

  $btnDefault = New-Object System.Windows.Forms.Button
  $btnDefault.Location = New-Object System.Drawing.Point(170, 300)
  $btnDefault.Size = New-Object System.Drawing.Size(140, 35)
  $btnDefault.Text = "Switch to Default"
  $btnDefault.Add_Click({
    Switch-Profile "default" $false
    $statusLabel.Text = "Current: default | Model: $(Get-CurrentModel)"
  })
  $form.Controls.Add($btnDefault)

  $btnShimRestart = New-Object System.Windows.Forms.Button
  $btnShimRestart.Location = New-Object System.Drawing.Point(320, 300)
  $btnShimRestart.Size = New-Object System.Drawing.Size(150, 35)
  $btnShimRestart.Text = "Shim + Restart"
  $btnShimRestart.Add_Click({
    Switch-Profile "shim" $true
    $form.Close()
  })
  $form.Controls.Add($btnShimRestart)

  $btnDefaultRestart = New-Object System.Windows.Forms.Button
  $btnDefaultRestart.Location = New-Object System.Drawing.Point(20, 345)
  $btnDefaultRestart.Size = New-Object System.Drawing.Size(140, 35)
  $btnDefaultRestart.Text = "Default + Restart"
  $btnDefaultRestart.Add_Click({
    Switch-Profile "default" $true
    $form.Close()
  })
  $form.Controls.Add($btnDefaultRestart)

  $btnRestart = New-Object System.Windows.Forms.Button
  $btnRestart.Location = New-Object System.Drawing.Point(170, 345)
  $btnRestart.Size = New-Object System.Drawing.Size(140, 35)
  $btnRestart.Text = "Restart Codex"
  $btnRestart.Add_Click({
    Restart-Codex
  })
  $form.Controls.Add($btnRestart)

  $btnClose = New-Object System.Windows.Forms.Button
  $btnClose.Location = New-Object System.Drawing.Point(320, 345)
  $btnClose.Size = New-Object System.Drawing.Size(150, 35)
  $btnClose.Text = "Close"
  $btnClose.Add_Click({ $form.Close() })
  $form.Controls.Add($btnClose)

  # Info label
  $infoLabel = New-Object System.Windows.Forms.Label
  $infoLabel.Location = New-Object System.Drawing.Point(20, 395)
  $infoLabel.Size = New-Object System.Drawing.Size(450, 40)
  $infoLabel.Text = "Templates: $CODEX_DIR`nConfig: $CONFIG"
  $infoLabel.Font = New-Object System.Drawing.Font("Segoe UI", 7)
  $infoLabel.ForeColor = [System.Drawing.Color]::Gray
  $form.Controls.Add($infoLabel)

  $form.ShowDialog() | Out-Null
}

# --- Main -------------------------------------------------------------------

switch ($Command) {
  "status" {
    $text = Read-Config
    $profile = Get-CurrentProfile $text
    $model = Get-CurrentModel
    Write-Host $profile
    Write-Host "model: $model"
  }
  "default" { Switch-Profile "default" $Restart }
  "shim" { Switch-Profile "shim" $Restart }
  "toggle" {
    $text = Read-Config
    $profile = Get-CurrentProfile $text
    if ($profile -eq "shim") { Switch-Profile "default" $Restart }
    else { Switch-Profile "shim" $Restart }
  }
  "models" { List-Models $Menu }
  "model" {
    if (-not $RestArgs -or $RestArgs.Count -lt 1) { Die "Usage: model <slug>" }
    Ensure-ShimStarted
    Write-Model $RestArgs[0]
  }
  "gui" { Show-Gui }
  "help" { Write-Host @"
Usage: codex-profile-switcher.ps1 status
       codex-profile-switcher.ps1 default [-Restart]
       codex-profile-switcher.ps1 shim [-Restart]
       codex-profile-switcher.ps1 toggle [-Restart]
       codex-profile-switcher.ps1 models [-Menu]
       codex-profile-switcher.ps1 model <slug>
       codex-profile-switcher.ps1 gui

Writes model/model_provider directly into ~/.codex/config.toml
Templates at ~/.codex/default.config.toml and ~/.codex/shim.config.toml
Use 'gui' for the WinForms dialog (Windows 11 only, not WSL).
"@ }
  default { Die "Unknown command: $Command. Use 'help' for usage." }
}
