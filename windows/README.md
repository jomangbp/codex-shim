# Codex Profile Switcher for Windows 11 / WSL

Windows equivalent of the Mac AppleScript-based profile switcher. Lets you
switch between Codex's default (ChatGPT subscription) and shim (BYOK models)
profiles, select specific shim models, and restart Codex — all from a GUI or
command line.

## Quick Start

### Windows 11 (native)

```powershell
# Install
cd codex-shim\windows
powershell -ExecutionPolicy Bypass -File install.ps1

# Open GUI
codex-profile-switcher gui

# Or use CLI
codex-profile-switcher status
codex-profile-switcher models
codex-profile-switcher model cline-pass/glm-5.2
codex-profile-switcher shim --restart
```

A desktop shortcut is created automatically for the GUI.

### WSL (Ubuntu/Debian inside Windows)

```bash
# Install
cd codex-shim/windows
powershell.exe -ExecutionPolicy Bypass -File install.ps1

# Or use directly from WSL bash:
powershell.exe -ExecutionPolicy Bypass -File ~/.local/bin/codex-profile-switcher.ps1 models
```

In WSL, the GUI (`gui` command) is not available (no WinForms). Use the CLI
commands instead. The script auto-detects WSL and uses Linux paths.

## Prerequisites

1. **Codex Desktop** installed on Windows
2. **codex-shim** cloned to `~/.local/src/codex-shim` (or `%USERPROFILE%\.local\src\codex-shim`)
3. **Python 3.10+** with `pip install -e .` run in the codex-shim repo
4. **models.json** at `~/.codex-shim/models.json` with your BYOK model configs
5. **PowerShell 5.1+** (built into Windows 11)

## Commands

| Command | Description |
|---------|-------------|
| `status` | Show current profile and model |
| `default [-Restart]` | Switch to OpenAI default profile |
| `shim [-Restart]` | Switch to codex-shim profile |
| `toggle [-Restart]` | Toggle between default and shim |
| `models [-Menu]` | List available shim models |
| `model <slug>` | Set specific model (e.g. `cline-pass/glm-5.2`) |
| `gui` | Open WinForms dialog (Windows 11 only) |
| `help` | Show usage |

## Configuration

The switcher manages `~/.codex/config.toml` (or `%USERPROFILE%\.codex\config.toml`)
and uses templates at:

- `~/.codex/default.config.toml` — default OpenAI profile
- `~/.codex/shim.config.toml` — shim profile template

The shim catalog is read from `~/.local/src/codex-shim/.codex-shim/custom_model_catalog.json`.

## ClinePass Models

If you have `cline` CLI installed and authenticated (`cline auth cline`), the
ClinePass models are automatically available:

- `cline-pass/qwen3.7-max`
- `cline-pass/glm-5.2`
- `cline-pass/kimi-k2.7-code`
- `cline-pass/deepseek-v4-pro`
- `cline-pass/minimax-m3`
- and more

These are routed through the Cline subscription API at `https://api.cline.bot/api/v1`.

## Differences from Mac version

- Mac uses AppleScript dialogs; Windows uses WinForms (PowerShell)
- Mac has a `.app` bundle; Windows has a desktop shortcut
- WSL mode auto-detected — uses Linux paths, CLI only (no GUI)
- The underlying codex-shim server is the same Python code on all platforms
