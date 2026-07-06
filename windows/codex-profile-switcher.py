#!/usr/bin/env python3
"""Codex profile switcher for Windows 11 / WSL — cross-platform Python version.

This is a portable alternative to the PowerShell GUI that works in WSL
(where WinForms is not available). It provides a simple TUI (text UI) for
model selection and profile switching.

Usage:
  codex-profile-switcher.py status
  codex-profile-switcher.py default [--restart]
  codex-profile-switcher.py shim [--restart]
  codex-profile-switcher.py toggle [--restart]
  codex-profile-switcher.py models [--menu]
  codex-profile-switcher.py model <slug>
  codex-profile-switcher.py tui
"""
from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CODEX_DIR = HOME / ".codex"
CONFIG = CODEX_DIR / "config.toml"
DEFAULT_TEMPLATE = CODEX_DIR / "default.config.toml"
SHIM_TEMPLATE = CODEX_DIR / "shim.config.toml"
BACKUP_DIR = CODEX_DIR / "profile-switcher-backups"

SHIM_REPO = HOME / ".local" / "src" / "codex-shim"
SHIM_CATALOG = str(SHIM_REPO / ".codex-shim" / "custom_model_catalog.json")
SHIM_PROVIDER = "codex_shim"
SHIM_BASE_URL = "http://127.0.0.1:8765/v1"

MANAGED_BEGIN = "# >>> codex-profile-switcher managed >>>"
MANAGED_END = "# <<< codex-profile-switcher managed <<<"
CODEX_SHIM_BEGIN = "# >>> codex-shim managed >>>"
CODEX_SHIM_END = "# <<< codex-shim managed <<<"

IS_WINDOWS = platform.system() == "Windows"
IS_WSL = os.path.exists("/proc/version") and "microsoft" in Path("/proc/version").read_text().lower()


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def read_config() -> str:
    if not CONFIG.exists():
        return ""
    return CONFIG.read_text()


def backup(text: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"config.toml.{stamp}.bak"
    path.write_text(text)
    return path


def remove_marked_blocks(text: str, begin: str, end: str) -> str:
    while begin in text:
        before, rest = text.split(begin, 1)
        if end not in rest:
            return before.rstrip() + "\n"
        _, after = rest.split(end, 1)
        text = before + after
    return text


def remove_section(text: str, section: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skipping = False
    header = f"[{section}]"
    for line in lines:
        if line.strip() == header:
            skipping = True
            continue
        if skipping and line.strip().startswith("[") and line.strip() != header:
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def current_profile(text: str) -> str:
    import re
    m = re.search(r"(?s)" + re.escape(MANAGED_BEGIN) + r"(.*?)" + re.escape(MANAGED_END), text)
    if m:
        block = m.group(1)
        if 'profile = "shim"' in block:
            return "shim"
        if 'profile = "default"' in block:
            return "default"
    if re.search(r'model_provider\s*=\s*"(codex_shim|factory_byok_shim)"', text):
        return "shim"
    return "default"


def current_model() -> str:
    import re
    text = read_config()
    m = re.search(r'model\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def ensure_shim_started() -> None:
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3)
        return
    except Exception:
        pass

    settings_path = str(HOME / ".codex-shim" / "models.json")
    venv_python = SHIM_REPO / ".venv" / ("Scripts" / "python.exe" if IS_WINDOWS else "bin" / "python")
    python_bin = str(venv_python) if venv_python.exists() else "python3"

    subprocess.Popen(
        [python_bin, "-m", "codex_shim.server", "--settings", settings_path,
         "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(SHIM_REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(15):
        time.sleep(1)
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
            print("Shim started.")
            return
        except Exception:
            pass
    print("Shim failed to start within 15s.", file=sys.stderr)


def restart_codex() -> None:
    if IS_WSL:
        print("In WSL, restart Codex by closing and reopening your terminal session.")
        return

    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", "Codex.exe"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass
        time.sleep(2)

        paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Codex", "Codex.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Codex", "Codex.exe"),
        ]
        for p in paths:
            if os.path.exists(p):
                subprocess.Popen([p])
                print(f"Started Codex from {p}")
                return
        print("Codex executable not found. Start it manually.")
    else:
        # Mac/Linux
        try:
            subprocess.run(["pkill", "-f", "Codex"], timeout=10)
        except Exception:
            pass
        time.sleep(2)
        subprocess.Popen(["open", "-a", "Codex"])


def ensure_templates() -> None:
    if not DEFAULT_TEMPLATE.exists():
        DEFAULT_TEMPLATE.write_text(
            '# Codex default profile — uses OpenAI ChatGPT subscription\n'
            'model = "gpt-5.5"\n'
            'model_provider = "openai"\n'
        )
    if not SHIM_TEMPLATE.exists():
        SHIM_TEMPLATE.write_text(
            f'{CODEX_SHIM_BEGIN}\n'
            f'model = "kimi-k2-7-code-cloud"\n'
            f'model_provider = "{SHIM_PROVIDER}"\n'
            f'model_catalog_json = "{SHIM_CATALOG}"\n\n'
            f'[model_providers.{SHIM_PROVIDER}]\n'
            f'name = "Codex Shim"\n'
            f'base_url = "{SHIM_BASE_URL}"\n'
            f'wire_api = "responses"\n'
            f'experimental_bearer_token = "dummy"\n'
            f'request_max_retries = 3\n'
            f'stream_max_retries = 3\n'
            f'stream_idle_timeout_ms = 600000\n'
            f'{CODEX_SHIM_END}\n'
        )


def write_model(slug: str) -> None:
    import re
    text = read_config()
    backup(text)
    text = re.sub(r'(?m)^model\s*=\s*"[^"]*"\s*\n', "", text)
    text = re.sub(r'(?m)^model_provider\s*=\s*"[^"]*"\s*\n', "", text)
    text = re.sub(r'(?m)^model_catalog_json\s*=\s*"[^"]*"\s*\n', "", text)
    text = remove_marked_blocks(text, CODEX_SHIM_BEGIN, CODEX_SHIM_END)

    model_block = f'model = "{slug}"\nmodel_provider = "{SHIM_PROVIDER}"\nmodel_catalog_json = "{SHIM_CATALOG}"\n'
    provider_block = (
        f'{CODEX_SHIM_BEGIN}\n'
        f'[model_providers.{SHIM_PROVIDER}]\n'
        f'name = "Codex Shim"\n'
        f'base_url = "{SHIM_BASE_URL}"\n'
        f'wire_api = "responses"\n'
        f'experimental_bearer_token = "dummy"\n'
        f'request_max_retries = 3\n'
        f'stream_max_retries = 3\n'
        f'stream_idle_timeout_ms = 600000\n'
        f'{CODEX_SHIM_END}\n'
    )
    text = model_block + "\n" + text.lstrip() + "\n" + provider_block + "\n"
    CONFIG.write_text(text)
    print(f"Shim model set to: {slug}")
    print("(applied to active config.toml)")


def load_models() -> list[dict]:
    try:
        data = json.loads(Path(SHIM_CATALOG).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        # Try fetching from the shim API
        try:
            import urllib.request
            resp = urllib.request.urlopen("http://127.0.0.1:8765/api/models", timeout=5)
            data = json.loads(resp.read())
            return data
        except Exception:
            print("No model catalog found. Run `codex-shim generate` first.", file=sys.stderr)
            raise SystemExit(1)
    return data.get("models", [])


def list_models(menu: bool = False) -> None:
    active = current_model()
    models = load_models()
    if menu:
        for m in models:
            slug = m.get("slug", "?")
            name = m.get("display_name", slug)
            suffix = " [active]" if slug == active else ""
            print(f"{slug} | {name}{suffix}")
        return
    width = max((len(m.get("slug", "")) for m in models), default=4)
    for m in models:
        slug = m.get("slug", "?")
        name = m.get("display_name", slug)
        marker = " *" if slug == active else "  "
        print(f"{marker} {slug:<{width}}  {name}")


def switch(profile: str, do_restart: bool) -> None:
    ensure_templates()
    text = read_config()
    backup(text)

    if profile == "shim":
        ensure_shim_started()
        shim_text = SHIM_TEMPLATE.read_text()
        import re
        m = re.search(r'model\s*=\s*"([^"]+)"', shim_text)
        if m:
            write_model(m.group(1))
        print("Switched to shim profile.")
    elif profile == "default":
        default_text = DEFAULT_TEMPLATE.read_text()
        text = remove_marked_blocks(text, CODEX_SHIM_BEGIN, CODEX_SHIM_END)
        text = remove_section(text, f"model_providers.{SHIM_PROVIDER}")
        import re
        text = re.sub(r'(?m)^model_provider\s*=.*\n', "", text)
        text = default_text + "\n" + text
        CONFIG.write_text(text)
        print("Switched to default profile.")

    if do_restart:
        restart_codex()


def show_tui() -> None:
    """Simple text-based UI for model selection."""
    print("=" * 60)
    print("  Codex Profile Switcher (TUI)")
    print("=" * 60)
    text = read_config()
    prof = current_profile(text)
    mdl = current_model()
    print(f"  Current: {prof} | Model: {mdl}")
    print("-" * 60)
    print()
    print("  Actions:")
    print("  1. Select Shim Model")
    print("  2. Switch to Shim")
    print("  3. Switch to Default")
    print("  4. Switch to Shim + Restart Codex")
    print("  5. Switch to Default + Restart Codex")
    print("  6. Restart Codex")
    print("  7. Show Current Profile")
    print("  0. Cancel")
    print()
    choice = input("  Choice: ").strip()

    if choice == "1":
        models = load_models()
        active = current_model()
        print()
        for i, m in enumerate(models):
            slug = m.get("slug", "?")
            name = m.get("display_name", slug)
            marker = " *" if slug == active else ""
            print(f"  {i + 1:2d}. {name} ({slug}){marker}")
        print()
        sel = input("  Select model number: ").strip()
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(models):
                slug = models[idx].get("slug", "")
                ensure_shim_started()
                write_model(slug)
                do_switch = input(f"\n  Switch to shim now? (y/n): ").strip().lower()
                if do_switch == "y":
                    switch("shim", False)
        except (ValueError, IndexError):
            print("Invalid selection.")
    elif choice == "2":
        switch("shim", False)
    elif choice == "3":
        switch("default", False)
    elif choice == "4":
        switch("shim", True)
    elif choice == "5":
        switch("default", True)
    elif choice == "6":
        restart_codex()
    elif choice == "7":
        print(f"  Current profile: {prof}")
        print(f"  Current model: {mdl}")
    elif choice == "0":
        print("Cancelled.")
    else:
        print("Invalid choice.")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"help", "--help", "-h"}:
        print(__doc__)
        return 0

    cmd = argv[0]
    do_restart = "--restart" in argv or "-r" in argv

    if cmd == "status":
        text = read_config()
        print(current_profile(text))
        print(f"model: {current_model()}")
    elif cmd == "default":
        switch("default", do_restart)
    elif cmd == "shim":
        switch("shim", do_restart)
    elif cmd == "toggle":
        text = read_config()
        prof = current_profile(text)
        switch("default" if prof == "shim" else "shim", do_restart)
    elif cmd == "models":
        list_models("--menu" in argv)
    elif cmd == "model":
        if len(argv) < 2:
            die("Usage: model <slug>")
        ensure_shim_started()
        write_model(argv[1])
    elif cmd == "tui":
        show_tui()
    else:
        die(f"Unknown command: {cmd}. Use 'help' for usage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
