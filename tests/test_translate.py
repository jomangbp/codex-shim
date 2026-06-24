from __future__ import annotations

from codex_shim.translate import (
    anthropic_messages_to_chat,
    anthropic_to_response,
    chat_completion_to_anthropic_message,
    chat_completion_to_response,
    responses_to_anthropic,
    responses_to_chat,
)


def test_responses_to_chat_text_input():
    body = {"model": "slug", "instructions": "System", "input": "Hello", "stream": True, "max_output_tokens": 99}
    out = responses_to_chat(body, "real-model")
    assert out["model"] == "real-model"
    assert out["stream"] is True
    assert out["max_tokens"] == 99
    assert out["messages"] == [{"role": "system", "content": "System"}, {"role": "user", "content": "Hello"}]


def test_anthropic_messages_to_chat_preserves_tools_images_and_tool_results():
    body = {
        "model": "slug",
        "system": [{"type": "text", "text": "System"}],
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "repo"}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [
                            {"type": "text", "text": "result"},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "BBB"}},
                        ],
                    },
                    {"type": "text", "text": "Next"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}},
                ],
            },
        ],
        "max_tokens": 99,
        "stop_sequences": ["END"],
        "stream": True,
        "tools": [{"name": "lookup", "description": "Lookup", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "tool", "name": "lookup"},
    }

    out = anthropic_messages_to_chat(body, "real-model")

    assert out["model"] == "real-model"
    assert out["max_tokens"] == 99
    assert out["stop"] == ["END"]
    assert out["stream_options"] == {"include_usage": True}
    assert out["tool_choice"] == {"type": "function", "function": {"name": "lookup"}}
    assert out["tools"] == [
        {
            "type": "function",
            "function": {"name": "lookup", "description": "Lookup", "parameters": {"type": "object"}},
        }
    ]
    assert out["messages"] == [
        {"role": "system", "content": "System"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "toolu_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":\"repo\"}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "content": "result\n[image]"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Visual tool result for toolu_1."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBB"}},
                {"type": "text", "text": "Next"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
            ],
        },
    ]


def test_chat_completion_to_anthropic_message_preserves_text_tools_and_usage():
    payload = {
        "id": "chatcmpl_fake",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "hello",
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":\"repo\"}"}},
                        {"id": "call_2", "type": "function", "function": {"name": "broken", "arguments": "{"}},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }

    out = chat_completion_to_anthropic_message(payload, "shim-model")

    assert out["id"] == "chatcmpl_fake"
    assert out["type"] == "message"
    assert out["role"] == "assistant"
    assert out["model"] == "shim-model"
    assert out["stop_reason"] == "tool_use"
    assert out["usage"] == {"input_tokens": 4, "output_tokens": 2}
    assert out["content"] == [
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "id": "call_1", "name": "lookup", "input": {"q": "repo"}},
        {"type": "tool_use", "id": "call_2", "name": "broken", "input": {"_raw": "{"}},
    ]



def test_chat_completion_to_anthropic_message_tool_only_uses_empty_content():
    payload = {
        "id": "chatcmpl_tool_only",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":\"repo\"}"}},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }

    out = chat_completion_to_anthropic_message(payload, "shim-model")

    assert out["content"] == [
        {"type": "tool_use", "id": "call_1", "name": "lookup", "input": {"q": "repo"}},
    ]
    assert out["stop_reason"] == "tool_use"


def test_chat_completion_to_anthropic_message_includes_reasoning():
    payload = {
        "id": "chatcmpl_reason",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "thinking hard",
                },
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }

    out = chat_completion_to_anthropic_message(payload, "shim-model")

    assert out["content"] == [
        {"type": "thinking", "thinking": "thinking hard"},
        {"type": "text", "text": "answer"},
    ]

def test_responses_to_chat_preserves_reasoning_and_effort_for_deepseek():
    body = {
        "model": "slug",
        "reasoning_effort": "high",
        "input": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "prior thought"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "prior answer"}]},
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "next"}]},
        ],
    }

    out = responses_to_chat(body, "deepseek-reasoner")

    assert out["reasoning_effort"] == "high"
    assert out["messages"] == [
        {"role": "assistant", "content": "prior answer", "reasoning_content": "prior thought"},
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "next"},
    ]


def test_responses_to_chat_strips_reasoning_effort_when_no_reasoning():
    """For models that cannot honor reasoning_effort, the shim removes the
    parameter entirely instead of forwarding it to the upstream endpoint."""
    body = {
        "model": "slug",
        "reasoning_effort": "high",
        "input": [{"role": "user", "content": "hi"}],
    }
    out = responses_to_chat(body, "llama3.2", no_reasoning=True)
    assert "reasoning_effort" not in out


def test_responses_to_chat_clamps_xhigh_and_minimal_effort():
    """Non-Ollama chat endpoints receive clamped reasoning_effort values because
    xhigh and minimal are not in the standard OpenAI chat enum."""
    body_xhigh = {"model": "slug", "reasoning_effort": "xhigh", "input": [{"role": "user", "content": "hi"}]}
    out_xhigh = responses_to_chat(body_xhigh, "deepseek-reasoner")
    assert out_xhigh["reasoning_effort"] == "high"

    body_minimal = {"model": "slug", "reasoning_effort": "minimal", "input": [{"role": "user", "content": "hi"}]}
    out_minimal = responses_to_chat(body_minimal, "deepseek-reasoner")
    assert out_minimal["reasoning_effort"] == "low"


def test_chat_completion_to_response_omits_reasoning_when_no_reasoning():
    """When no_reasoning is enabled, reasoning fields in the upstream response
    are omitted from the Codex Desktop response to avoid long thinking bubbles."""
    payload = {
        "id": "chatcmpl_no_reason",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "thinking hard",
                },
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    out = chat_completion_to_response(payload, "slug", no_reasoning=True)
    assert out["output"][0]["content"][0]["text"] == "answer"
    # The reasoning item should not appear in the output array.
    assert not any(item.get("type") == "reasoning" for item in out["output"])


def test_responses_to_chat_sanitizes_and_merges_strict_provider_messages():
    body = {
        "model": "slug",
        "instructions": "System\x00one",
        "input": [
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules\x00two"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi\x00"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "again\x01"}]},
            {"type": "function_call", "call_id": "call\x000", "name": "tool", "arguments": "{\"x\":\"y\x00\"}"},
        ],
    }

    out = responses_to_chat(body, "kimi-k2")

    assert out["messages"] == [
        {"role": "system", "content": "Systemone\n\nrulestwo"},
        {"role": "user", "content": "hi\n\nagain"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call0", "type": "function", "function": {"name": "tool", "arguments": "{\"x\":\"y\"}"}}
            ],
        },
    ]


def test_responses_function_tools_convert_to_chat_shape():
    body = {
        "model": "slug",
        "input": "Hi",
        "tools": [{"type": "function", "name": "do_work", "description": "Do work", "parameters": {"type": "object"}}],
    }
    out = responses_to_chat(body, "real-model")
    assert out["tools"] == [
        {
            "type": "function",
            "function": {"name": "do_work", "description": "Do work", "parameters": {"type": "object"}},
        }
    ]


def test_native_responses_tools_get_function_fallbacks_for_byok_chat():
    body = {
        "model": "slug",
        "input": "Use the browser",
        "tool_choice": {"type": "computer_use_preview"},
        "tools": [
            {"type": "computer_use_preview"},
            {"type": "web_search_preview"},
            {"type": "apply_patch"},
            {"type": "function", "name": "list_mcp_resources", "parameters": {"type": "object"}},
        ],
    }

    out = responses_to_chat(body, "real-model")

    functions = [tool["function"] for tool in out["tools"]]
    assert [fn["name"] for fn in functions] == ["computer_use", "web_search", "apply_patch", "list_mcp_resources"]
    assert functions[0]["parameters"]["required"] == ["action"]
    assert functions[1]["parameters"]["required"] == ["query"]
    assert functions[2]["parameters"]["required"] == ["patch"]
    assert out["tool_choice"] == {"type": "function", "function": {"name": "computer_use"}}


def test_native_responses_tools_get_anthropic_fallbacks():
    body = {
        "model": "slug",
        "input": "Search",
        "tools": [{"type": "web_search_preview"}, {"type": "computer_use_preview"}],
    }

    out = responses_to_anthropic(body, "claude-real", 123)

    assert [tool["name"] for tool in out["tools"]] == ["web_search", "computer_use"]
    assert out["tools"][0]["input_schema"]["required"] == ["query"]
    assert out["tools"][1]["input_schema"]["required"] == ["action"]


def test_responses_to_anthropic_messages():
    body = {"model": "slug", "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}]}
    out = responses_to_anthropic(body, "claude-real", 123)
    assert out["model"] == "claude-real"
    assert out["max_tokens"] == 123
    assert out["messages"] == [{"role": "user", "content": "Hi"}]


def test_responses_to_chat_preserves_input_images_for_vision_models():
    body = {
        "model": "slug",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "What is visible?"},
                    {"type": "input_image", "image_url": "data:image/png;base64,AAA", "detail": "high"},
                ],
            }
        ],
    }

    out = responses_to_chat(body, "vision-model")

    assert out["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is visible?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA", "detail": "high"}},
            ],
        }
    ]


def test_responses_to_chat_normalises_original_image_detail():
    """Codex Desktop sends `detail: "original"` on input_image items, but
    "original" is not a valid OpenAI Chat Completions value. Providers like
    Kimi K2.6 (via Ark) reject it with:

    The parameter `messages.content.image_url.detail` specified in the
    request are not valid: invalid value: `original`, supported values
    are: `low`, `high`, `xhigh`, and `auto`.

    The shim must translate ``original`` to ``high`` (the closest standard
    OpenAI value — "full resolution") rather than passing it through verbatim.
    """
    body = {
        "model": "slug",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe the screenshot"},
                    {"type": "input_image", "image_url": "data:image/png;base64,ZZZ", "detail": "original"},
                ],
            }
        ],
    }

    out = responses_to_chat(body, "vision-model")

    assert out["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe the screenshot"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZZZ", "detail": "high"}},
            ],
        }
    ]


def test_computer_call_output_screenshot_reaches_openai_chat_vision():
    body = {
        "model": "slug",
        "input": [
            {"type": "computer_call_output", "call_id": "cu_1", "output": {"type": "input_image", "image_url": "data:image/png;base64,BBB"}}
        ],
    }

    out = responses_to_chat(body, "vision-model")

    assert out["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Computer output for cu_1."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBB"}},
            ],
        }
    ]


def test_function_call_output_visual_feedback_adds_followup_image_message():
    body = {
        "model": "slug",
        "input": [
            {"type": "function_call", "call_id": "call_1", "name": "computer_use", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call_1", "output": [{"type": "input_image", "image_url": "data:image/png;base64,CCC"}]},
        ],
    }

    out = responses_to_chat(body, "vision-model")

    assert out["messages"][1] == {"role": "tool", "tool_call_id": "call_1", "content": "[image]"}
    assert out["messages"][2] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "Visual tool output for call_1."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,CCC"}},
        ],
    }


def test_responses_to_anthropic_preserves_visual_feedback_as_image_blocks():
    body = {
        "model": "slug",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Inspect this."},
                    {"type": "input_image", "image_url": "data:image/png;base64,DDD"},
                ],
            },
            {"type": "computer_call_output", "call_id": "cu_2", "output": {"type": "input_image", "image_url": "https://example.invalid/screen.png"}},
        ],
    }

    out = responses_to_anthropic(body, "claude-real", 123)

    assert out["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this."},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "DDD"}},
                {"type": "text", "text": "Computer output for cu_2."},
                {"type": "image", "source": {"type": "url", "url": "https://example.invalid/screen.png"}},
            ],
        }
    ]


def test_chat_completion_to_response_strips_think():
    payload = {
        "id": "chatcmpl_1",
        "choices": [{"message": {"role": "assistant", "content": "<think>secret</think>Hello"}}],
    }
    out = chat_completion_to_response(payload, "slug")
    assert out["model"] == "slug"
    assert out["output"][0]["content"][0]["text"] == "Hello"


def test_chat_completion_to_response_normalizes_cached_usage():
    payload = {
        "id": "chatcmpl_1",
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "prompt_tokens_details": {"cached_tokens": 8},
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }

    out = chat_completion_to_response(payload, "slug")

    assert out["usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "input_tokens_details": {"cached_tokens": 8},
        "output_tokens_details": {"reasoning_tokens": 1},
    }


def test_anthropic_to_response_normalizes_cache_usage():
    payload = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "Hello"}],
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 8,
            "cache_creation_input_tokens": 2,
            "output_tokens": 3,
        },
    }

    out = anthropic_to_response(payload, "slug")

    assert out["usage"] == {
        "input_tokens": 10,
        "output_tokens": 3,
        "total_tokens": 13,
        "input_tokens_details": {
            "cached_tokens": 8,
            "cache_read_input_tokens": 8,
            "cache_creation_input_tokens": 2,
        },
    }


# --- web_search_call round-trip tests ---

def test_responses_input_handles_web_search_call_as_function_call():
    """web_search_call items in the input should be translated to assistant
    tool_calls so the upstream chat-completions API sees a valid pairing
    with the subsequent function_call_output (tool message)."""
    from codex_shim.translate import _responses_input_to_messages

    input_items = [
        {"type": "message", "role": "user", "content": "search for OpenAI news"},
        {"type": "web_search_call", "call_id": "call_ws1", "name": "web_search", "arguments": '{"query": "OpenAI news"}'},
        {"type": "function_call_output", "call_id": "call_ws1", "output": "OpenAI announced GPT-5"},
        {"type": "message", "role": "user", "content": "what did it say?"},
    ]
    messages = _responses_input_to_messages(input_items)

    # Should produce: user, assistant(tool_calls), tool, user
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1].get("tool_calls")
    assert messages[1]["tool_calls"][0]["id"] == "call_ws1"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "web_search"
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == '{"query": "OpenAI news"}'
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_ws1"
    assert "OpenAI announced GPT-5" in messages[2]["content"]
    assert messages[3]["role"] == "user"


def test_responses_to_chat_translates_web_search_call_roundtrip():
    """Full roundtrip: responses_to_chat should convert a conversation
    containing web_search_call + function_call_output into valid
    chat-completions messages with matching tool_calls and tool messages."""
    from codex_shim.translate import responses_to_chat

    body = {
        "model": "test-model",
        "input": [
            {"type": "message", "role": "user", "content": "search for OpenAI"},
            {"type": "web_search_call", "call_id": "ws_abc", "name": "web_search", "arguments": '{"query": "OpenAI"}'},
            {"type": "function_call_output", "call_id": "ws_abc", "output": "GPT-5 is here"},
        ],
        "tools": [{"type": "web_search"}],
    }
    chat = responses_to_chat(body, "test-model")
    messages = chat["messages"]

    # Find the assistant message with tool_calls
    assistant_msgs = [m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")]
    assert len(assistant_msgs) == 1, f"Expected 1 assistant with tool_calls, got {len(assistant_msgs)}"
    tool_calls = assistant_msgs[0]["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "ws_abc"
    assert tool_calls[0]["function"]["name"] == "web_search"

    # Find the tool response message
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1, f"Expected 1 tool message, got {len(tool_msgs)}"
    assert tool_msgs[0]["tool_call_id"] == "ws_abc"
    assert "GPT-5 is here" in tool_msgs[0]["content"]
