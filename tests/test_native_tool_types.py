"""Tests for native tool type mapping in the streaming translator and non-streaming response helpers."""
from __future__ import annotations

import json
from codex_shim.translate import chat_completion_to_response, anthropic_to_response
from codex_shim.server import _build_tool_types


def test_build_tool_types_native_tools():
    """Native tools like apply_patch and web_search are preserved."""
    body = {
        "tools": [
            {"type": "apply_patch"},
            {"type": "web_search_preview"},
            {"type": "local_shell"},
        ]
    }
    tool_types = _build_tool_types(body)
    assert tool_types["apply_patch"] == "apply_patch"
    assert tool_types["web_search_preview"] == "web_search_preview"
    assert tool_types["local_shell"] == "local_shell"


def test_build_tool_types_mcp_tools():
    """MCP tools with function names are preserved."""
    body = {
        "tools": [
            {"type": "mcp__node_repl", "function": {"name": "js"}},
            {"type": "mcp__node_repl", "function": {"name": "eval"}},
        ]
    }
    tool_types = _build_tool_types(body)
    assert tool_types["js"] == "mcp__node_repl"
    assert tool_types["eval"] == "mcp__node_repl"


def test_build_tool_types_empty_and_missing():
    """Empty or missing tools arrays return empty dict."""
    assert _build_tool_types({}) == {}
    assert _build_tool_types({"tools": []}) == {}
    assert _build_tool_types({"tools": None}) == {}


def test_chat_completion_to_response_apply_patch_custom_tool_call():
    """apply_patch tool type maps to custom_tool_call output item."""
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "apply_patch", "arguments": '{"patch": "diff"}'},
                        }
                    ],
                }
            }
        ]
    }
    tool_types = {"apply_patch": "apply_patch"}
    response = chat_completion_to_response(payload, "model", tool_types)
    output = response["output"]
    call_items = [o for o in output if o["type"] in ("function_call", "custom_tool_call", "web_search_call")]
    assert len(call_items) == 1
    assert call_items[0]["type"] == "custom_tool_call"
    assert call_items[0]["name"] == "apply_patch"


def test_chat_completion_to_response_web_search_call():
    """web_search tool type maps to function_call output item (not web_search_call).

    Codex Desktop in BYOK mode drops function_call_output for web_search_call
    items, so we emit function_call instead to ensure results are round-tripped.
    """
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "function": {"name": "web_search", "arguments": '{"query": "test"}'},
                        }
                    ],
                }
            }
        ]
    }
    tool_types = {"web_search": "web_search"}
    response = chat_completion_to_response(payload, "model", tool_types)
    output = response["output"]
    call_items = [o for o in output if o["type"] in ("function_call", "custom_tool_call")]
    assert len(call_items) == 1
    assert call_items[0]["type"] == "function_call"
    assert call_items[0]["name"] == "web_search"


def test_chat_completion_to_response_unknown_tool_function_call():
    """Unknown tool types fall back to generic function_call."""
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_3",
                            "function": {"name": "random_tool", "arguments": '{"x": 1}'},
                        }
                    ],
                }
            }
        ]
    }
    tool_types = {"random_tool": "mcp__random"}
    response = chat_completion_to_response(payload, "model", tool_types)
    output = response["output"]
    call_items = [o for o in output if o["type"] in ("function_call", "custom_tool_call", "web_search_call")]
    assert len(call_items) == 1
    assert call_items[0]["type"] == "function_call"
    assert call_items[0]["name"] == "random_tool"


def test_anthropic_to_response_with_tool_types():
    """Anthropic path also maps apply_patch to custom_tool_call."""
    payload = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "tu_1", "name": "apply_patch", "input": {"patch": "diff"}},
        ],
        "id": "msg_1",
    }
    tool_types = {"apply_patch": "apply_patch"}
    response = anthropic_to_response(payload, "model", tool_types)
    output = response["output"]
    call_items = [o for o in output if o["type"] in ("function_call", "custom_tool_call", "web_search_call")]
    assert len(call_items) == 1
    assert call_items[0]["type"] == "custom_tool_call"


def test_chat_completion_to_response_no_tool_types_backward_compat():
    """Without tool_types, everything falls back to function_call (backward compat)."""
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "apply_patch", "arguments": '{"patch": "diff"}'},
                        }
                    ],
                }
            }
        ]
    }
    response = chat_completion_to_response(payload, "model")
    output = response["output"]
    call_items = [o for o in output if o["type"] in ("function_call", "custom_tool_call", "web_search_call")]
    assert len(call_items) == 1
    assert call_items[0]["type"] == "function_call"


# --- Streaming web search interception tests ---

import asyncio
from codex_shim.server import ResponsesStreamState


def test_streaming_web_search_interception_emits_function_call_output():
    """When a web_search_call is streamed, finish(intercept_web_search=True)
    should execute the search and emit function_call_output SSE events with
    the results, and those results should appear in response.completed output."""
    tool_types = {"web_search": "web_search"}
    state = ResponsesStreamState("test-model", tool_types)

    captured: list[dict] = []

    class FakeResponse:
        async def write(self, data: bytes) -> None:
            for line in data.decode().splitlines():
                line = line.strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        captured.append(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        pass

    async def run():
        fake = FakeResponse()
        await state.start(fake)

        # Simulate a streamed web_search tool call
        await state.write_chat_delta(fake, {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call_123",
                "function": {"name": "web_search", "arguments": '{"query": "test query"}'},
            }]}}]
        })

        # Mock the search to avoid network calls
        import codex_shim.server as srv
        original = srv._perform_web_search
        async def mock_search(q):
            return f"Mock results for: {q}"
        srv._perform_web_search = mock_search
        try:
            await state.finish(fake, intercept_web_search=True)
        finally:
            srv._perform_web_search = original

    asyncio.run(run())

    # Check that function_call_output events were emitted
    added_items = [e for e in captured if e.get("type") == "response.output_item.added"]
    done_items = [e for e in captured if e.get("type") == "response.output_item.done"]
    completed = [e for e in captured if e.get("type") == "response.completed"]

    # Find the function_call_output items
    fco_added = [e for e in added_items if e.get("item", {}).get("type") == "function_call_output"]
    fco_done = [e for e in done_items if e.get("item", {}).get("type") == "function_call_output"]

    assert len(fco_added) == 1, f"Expected 1 function_call_output added, got {len(fco_added)}"
    assert len(fco_done) == 1, f"Expected 1 function_call_output done, got {len(fco_done)}"
    assert fco_added[0]["item"]["call_id"] == "call_123"
    assert "Mock results for: test query" in fco_added[0]["item"]["output"]

    # Check that response.completed includes the search results in output
    assert len(completed) == 1
    output = completed[0]["response"]["output"]
    fco_in_output = [o for o in output if o.get("type") == "function_call_output"]
    assert len(fco_in_output) == 1
    assert fco_in_output[0]["call_id"] == "call_123"
    assert "Mock results for: test query" in fco_in_output[0]["output"]


def test_streaming_no_web_search_no_interception():
    """When no web_search_call is present, finish(intercept_web_search=True)
    should not emit any function_call_output items."""
    tool_types = {"apply_patch": "apply_patch"}
    state = ResponsesStreamState("test-model", tool_types)

    captured: list[dict] = []

    class FakeResponse:
        async def write(self, data: bytes) -> None:
            for line in data.decode().splitlines():
                line = line.strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        captured.append(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        pass

    async def run():
        fake = FakeResponse()
        await state.start(fake)
        # Simulate a normal function call (not web_search)
        await state.write_chat_delta(fake, {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call_456",
                "function": {"name": "apply_patch", "arguments": '{}'},
            }]}}]
        })
        await state.finish(fake, intercept_web_search=True)

    asyncio.run(run())

    completed = [e for e in captured if e.get("type") == "response.completed"]
    output = completed[0]["response"]["output"]
    fco_items = [o for o in output if o.get("type") == "function_call_output"]
    assert len(fco_items) == 0, f"Expected 0 function_call_output, got {fco_items}"
