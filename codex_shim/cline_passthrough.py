"""Cline subscription passthrough — routes ClinePass models through the Cline
subscription's OAuth-authenticated API (https://api.cline.bot/api/v1).

This mirrors the cursor_passthrough pattern: detect whether `cline` CLI is
installed and authenticated, expose the available ClinePass models as catalog
entries, and proxy chat-completions requests through the Cline API.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from dataclasses import dataclass, field

from .translate import responses_to_chat, strip_think


CLINE_API_BASE = "https://api.cline.bot/api/v1"
CLINE_SETTINGS_PATH = Path.home() / ".cline" / "data" / "settings" / "providers.json"
CLINE_RECOMMENDED_URL = f"{CLINE_API_BASE}/ai/cline/recommended-models"

CLINE_PASS_FALLBACK_MODELS: tuple[str, ...] = (
    "cline-pass/qwen3.7-max",
    "cline-pass/qwen3.7-plus",
    "cline-pass/minimax-m3",
    "cline-pass/mimo-v2.5-pro",
    "cline-pass/glm-5.2",
    "cline-pass/mimo-v2.5",
    "cline-pass/kimi-k2.7-code",
    "cline-pass/deepseek-v4-flash",
    "cline-pass/deepseek-v4-pro",
    "cline-pass/kimi-k2.6",
)

_model_cache: tuple[float, list[str]] | None = None
_MODEL_CACHE_TTL = 300.0


def _cline_settings_path() -> Path:
    override = os.environ.get("CLINE_SETTINGS_PATH", "").strip()
    return Path(override) if override else CLINE_SETTINGS_PATH


_CLINE_REFRESH_URL = "https://api.cline.bot/api/v1/auth/refresh"
_REFRESH_AHEAD_SEC = 60  # refresh 60 seconds before expiry


def _read_cline_auth() -> dict[str, Any] | None:
    """Read the Cline OAuth auth from ~/.cline/data/settings/providers.json."""
    path = _cline_settings_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    providers = data.get("providers") or {}
    cline = providers.get("cline") or {}
    settings = cline.get("settings") or {}
    auth = settings.get("auth") or {}
    token = auth.get("accessToken")
    if not token or not token.strip():
        return None
    return auth


def cline_passthrough_enabled() -> bool:
    return os.environ.get("CODEX_SHIM_DISABLE_CLINE", "").lower() not in {"1", "true", "yes", "on"}


def _read_full_cline_config() -> dict[str, Any] | None:
    """Read the full providers.json file."""
    path = _cline_settings_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cline_auth(new_auth: dict[str, Any]) -> None:
    """Persist updated auth data back to ~/.cline/data/settings/providers.json."""
    path = _cline_settings_path()
    config = _read_full_cline_config()
    if config is None:
        return
    providers = config.setdefault("providers", {})
    cline = providers.setdefault("cline", {})
    settings = cline.setdefault("settings", {})
    settings["auth"] = new_auth
    cline["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    try:
        path.write_text(json.dumps(config, indent=2) + "\n", "utf-8")
    except OSError:
        pass


def _is_token_expired(auth: dict[str, Any]) -> bool:
    """Check if the access token is expired or about to expire."""
    expires_at = auth.get("expiresAt")
    if not expires_at:
        return False
    # expiresAt can be in milliseconds (number) or ISO 8601 (string)
    if isinstance(expires_at, (int, float)):
        return time.time() * 1000 > expires_at - _REFRESH_AHEAD_SEC * 1000
    if isinstance(expires_at, str):
        try:
            from datetime import datetime, timezone
            # Handle both "2026-07-01T20:32:46Z" and other ISO formats
            dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return time.time() > dt.timestamp() - _REFRESH_AHEAD_SEC
        except (ValueError, TypeError):
            return False
    return False


def _refresh_cline_token(refresh_token: str) -> dict[str, Any] | None:
    """Refresh the Cline access token using the refresh token.

    Returns the new auth dict (accessToken, refreshToken, expiresAt) on success,
    or None on failure.
    """
    import urllib.request
    import urllib.error

    body = json.dumps({
        "refreshToken": refresh_token,
        "grantType": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(
        _CLINE_REFRESH_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict) or not data.get("success"):
        return None

    result = data.get("data") or {}
    access_token = result.get("accessToken")
    if not access_token:
        return None

    # Convert ISO expiry to milliseconds since epoch for consistency
    expires_at_str = result.get("expiresAt", "")
    expires_at_ms = 0
    if expires_at_str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            expires_at_ms = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            pass

    new_auth: dict[str, Any] = {
        "accessToken": f"workos:{access_token}" if not access_token.startswith("workos:") else access_token,
        "refreshToken": result.get("refreshToken", refresh_token),
        "expiresAt": expires_at_ms or expires_at_str,
        "accountId": result.get("userInfo", {}).get("clineUserId", ""),
    }
    return new_auth


def cline_passthrough_available() -> bool:
    """Return True when cline is installed and authenticated.

    Returns True even when the access token is expired, as long as a refresh
    token exists — the token will be auto-refreshed on next use.
    """
    if not cline_passthrough_enabled():
        return False
    auth = _read_cline_auth()
    if auth is None:
        return False
    # Available if we have an access token (even if expired, we can refresh)
    refresh = auth.get("refreshToken")
    if refresh and refresh.strip():
        return True
    # No refresh token — only available if access token is not expired
    expires_at = auth.get("expiresAt")
    if isinstance(expires_at, (int, float)) and expires_at > 0:
        return time.time() * 1000 <= expires_at
    return True


def _get_cline_token() -> str | None:
    """Get a valid (possibly refreshed) Cline access token."""
    auth = _read_cline_auth()
    if auth is None:
        return None

    # If token is still valid, return it
    if not _is_token_expired(auth):
        return auth.get("accessToken", "").strip() or None

    # Token is expired — try to refresh
    refresh_token = auth.get("refreshToken", "").strip()
    if not refresh_token:
        return auth.get("accessToken", "").strip() or None

    new_auth = _refresh_cline_token(refresh_token)
    if new_auth is None:
        # Refresh failed — return the stale token (may still work briefly)
        return auth.get("accessToken", "").strip() or None

    _save_cline_auth(new_auth)
    return new_auth.get("accessToken", "").strip() or None


def cline_passthrough_slugs() -> set[str]:
    return set(cline_pass_model_ids())


def cline_passthrough_display_names() -> dict[str, str]:
    result: dict[str, str] = {}
    for model_id in cline_pass_model_ids():
        short = model_id.split("/", 1)[-1] if "/" in model_id else model_id
        result[model_id] = short
    return result


def is_cline_passthrough_slug(slug: str) -> bool:
    return slug in cline_passthrough_slugs()


def cline_upstream_model(slug: str) -> str:
    """For Cline, the slug IS the model ID (e.g. 'cline-pass/glm-5.2')."""
    return slug


def cline_pass_model_ids() -> list[str]:
    """Return the list of ClinePass model IDs.

    Uses a cached fetch from the Cline API if available, otherwise falls back
    to the hardcoded list.
    """
    global _model_cache
    now = time.monotonic()
    if _model_cache is not None:
        cached_at, cached = _model_cache
        if now - cached_at < _MODEL_CACHE_TTL:
            return cached

    token = _get_cline_token()
    if token:
        try:
            import urllib.request

            req = urllib.request.Request(
                CLINE_RECOMMENDED_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cline_pass = data.get("clinePass") or []
            model_ids = [str(m.get("id", "")) for m in cline_pass if m.get("id")]
            if model_ids:
                _model_cache = (now, model_ids)
                return model_ids
        except Exception:
            pass

    fallback = list(CLINE_PASS_FALLBACK_MODELS)
    _model_cache = (now, fallback)
    return fallback


def _cline_catalog_entry(model_id: str) -> dict[str, Any]:
    short = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    return {
        "slug": model_id,
        "display_name": short,
        "description": f"ClinePass model {short} routed through your Cline subscription.",
        "context_window": 128_000,
        "max_context_window": 128_000,
        "auto_compact_token_limit": 102_400,
        "truncation_policy": {"mode": "tokens", "limit": 32_000},
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Faster, lighter reasoning"},
            {"effort": "medium", "description": "Balanced speed and reasoning"},
            {"effort": "high", "description": "Deeper reasoning"},
        ],
        "default_reasoning_summary": "none",
        "reasoning_summary_format": "none",
        "supports_reasoning_summaries": False,
        "default_verbosity": "low",
        "support_verbosity": False,
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text_and_image",
        "supports_search_tool": False,
        "supports_parallel_tool_calls": True,
        "experimental_supported_tools": [],
        "input_modalities": ["text", "image"],
        "supports_image_detail_original": True,
        "shell_type": "shell_command",
        "visibility": "list",
        "minimal_client_version": "0.0.1",
        "supported_in_api": True,
        "availability_nux": None,
        "upgrade": None,
        "priority": 10_000,
        "prefer_websockets": False,
        "available_in_plans": ["free", "plus", "pro", "team", "business", "enterprise"],
        "base_instructions": f"You are Codex, a coding agent powered by {short}.",
        "model_messages": {
            "instructions_template": f"You are Codex, a coding agent powered by {short}.",
            "instructions_variables": {"model_name": short},
        },
    }


def cline_catalog_entries() -> list[dict[str, Any]]:
    """Return catalog entries for all available ClinePass models."""
    return [_cline_catalog_entry(mid) for mid in cline_pass_model_ids()]


def _build_cline_chat_body(body: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Convert a Codex Responses payload into a Cline chat-completions body."""
    chat = responses_to_chat(body, model_id)
    chat["model"] = model_id
    chat.pop("reasoning_effort", None)
    chat.pop("reasoning", None)
    return chat


async def iter_cline_chat_events(
    body: dict[str, Any], model_id: str
) -> AsyncIterator[dict[str, Any]]:
    """Send a chat-completions request to the Cline API and yield normalized events.

    Yields events:
    - {"type": "text_delta", "delta": str}
    - {"type": "usage", "usage": dict}
    - {"type": "error", "message": str}
    - {"type": "completed", "text": str}
    """
    from aiohttp import ClientSession, ClientTimeout

    token = _get_cline_token()
    if not token:
        yield {"type": "error", "message": "Cline is not authenticated. Run `cline auth cline`."}
        return

    chat_body = _build_cline_chat_body(body, model_id)
    stream = bool(body.get("stream"))
    url = f"{CLINE_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    timeout = ClientTimeout(total=300)
    async with ClientSession(timeout=timeout) as session:
        upstream = await session.post(url, json=chat_body, headers=headers)
        if upstream.status >= 400:
            error_text = await upstream.text()
            yield {"type": "error", "message": f"Cline API error {upstream.status}: {error_text[:500]}"}
            return

        if stream:
            full_text = ""
            usage: dict[str, Any] | None = None
            async for line in upstream.content:
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str or line_str == "data: [DONE]":
                    continue
                if line_str.startswith("data: "):
                    line_str = line_str[6:]
                try:
                    chunk = json.loads(line_str)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if "data" in chunk and isinstance(chunk["data"], dict):
                    chunk = chunk["data"]
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        full_text += content
                        yield {"type": "text_delta", "delta": content}
                    for tc in delta.get("tool_calls") or []:
                        if isinstance(tc, dict):
                            yield {"type": "tool_call", "tool_call": tc}
                u = chunk.get("usage")
                if isinstance(u, dict):
                    usage = u
            if usage:
                yield {"type": "usage", "usage": usage}
            if full_text:
                yield {"type": "completed", "text": full_text}
        else:
            payload = await upstream.json(content_type=None)
            if isinstance(payload, dict) and "data" in payload:
                payload = payload["data"]
            choices = payload.get("choices") or []
            text = ""
            tool_calls: list[dict[str, Any]] = []
            if choices:
                msg = choices[0].get("message") or {}
                text = msg.get("content") or ""
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        tool_calls.append(tc)
            usage = payload.get("usage")
            if isinstance(usage, dict):
                yield {"type": "usage", "usage": usage}
            # Emit tool calls as events so the server can translate them
            for tc in tool_calls:
                yield {"type": "tool_call", "tool_call": tc}
            if text:
                yield {"type": "completed", "text": text}
            elif tool_calls:
                yield {"type": "completed", "text": ""}
            else:
                yield {"type": "error", "message": "Cline API returned empty response."}

        upstream.release()


def refresh_cline_model_cache() -> None:
    """Force a refresh of the Cline model cache."""
    global _model_cache
    _model_cache = None
    cline_pass_model_ids()


def _is_cline_auth_failure(text: str) -> bool:
    value = text.strip().lower()
    if not value:
        return False
    return any(
        marker in value
        for marker in (
            "not authenticated",
            "authentication required",
            "please run",
            "cline auth",
            "unauthorized",
        )
    )
