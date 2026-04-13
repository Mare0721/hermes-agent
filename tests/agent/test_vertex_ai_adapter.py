"""Tests for the Vertex AI chat-completions adapter."""

import asyncio
import base64
from unittest.mock import MagicMock, patch

import agent.models.vertex_ai as vertex_ai_module
from agent.models.vertex_ai import (
    VertexAIClient,
    _build_vertex_messages,
    _vertex_response_to_openai,
)


def test_build_vertex_messages_maps_system_and_tool_roundtrip():
    messages = [
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city":"SF"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"temp_c":21}',
        },
        {"role": "user", "content": "Thanks."},
    ]

    system_instruction, contents = _build_vertex_messages(messages)

    assert system_instruction == {"parts": [{"text": "You are concise."}]}
    assert [item["role"] for item in contents] == ["user", "model", "user"]

    final_user_parts = contents[-1]["parts"]
    assert any("functionResponse" in part for part in final_user_parts)
    assert any(part.get("text") == "Thanks." for part in final_user_parts)


def test_remote_image_runtime_config_resolves_from_env(monkeypatch):
    monkeypatch.setenv("HERMES_VERTEX_REMOTE_IMAGE_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("HERMES_VERTEX_REMOTE_IMAGE_CACHE_TTL_SECONDS", "55")
    monkeypatch.setenv("HERMES_VERTEX_REMOTE_IMAGE_CACHE_MAX_ENTRIES", "11")

    assert vertex_ai_module._resolve_remote_image_timeout_seconds() == 9.0
    assert vertex_ai_module._resolve_remote_image_cache_ttl_seconds() == 55.0
    assert vertex_ai_module._resolve_remote_image_cache_max_entries() == 11


def test_remote_image_runtime_config_resolves_from_config(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_VERTEX_REMOTE_IMAGE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HERMES_VERTEX_REMOTE_IMAGE_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("HERMES_VERTEX_REMOTE_IMAGE_CACHE_MAX_ENTRIES", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        (
            "auxiliary:\n"
            "  vision:\n"
            "    remote_image_timeout: 8\n"
            "    remote_image_cache_ttl: 44\n"
            "    remote_image_cache_max_entries: 9\n"
        ),
        encoding="utf-8",
    )

    assert vertex_ai_module._resolve_remote_image_timeout_seconds() == 8.0
    assert vertex_ai_module._resolve_remote_image_cache_ttl_seconds() == 44.0
    assert vertex_ai_module._resolve_remote_image_cache_max_entries() == 9


def test_remote_image_runtime_config_defaults_balanced():
    with (
        patch.dict(
            "os.environ",
            {
                "HERMES_VERTEX_REMOTE_IMAGE_TIMEOUT_SECONDS": "",
                "HERMES_VERTEX_REMOTE_IMAGE_CACHE_TTL_SECONDS": "",
                "HERMES_VERTEX_REMOTE_IMAGE_CACHE_MAX_ENTRIES": "",
            },
            clear=False,
        ),
        patch("agent.models.vertex_ai._read_auxiliary_vision_config", return_value={}),
    ):
        assert vertex_ai_module._resolve_remote_image_timeout_seconds() == 20.0
        assert vertex_ai_module._resolve_remote_image_cache_ttl_seconds() == 180.0
        assert vertex_ai_module._resolve_remote_image_cache_max_entries() == 96


def test_remote_image_runtime_config_logging_once():
    vertex_ai_module._REMOTE_IMAGE_RUNTIME_CONFIG_LOGGED = False

    with patch("agent.models.vertex_ai.logger.info") as mock_info:
        vertex_ai_module._log_remote_image_runtime_config_once()
        vertex_ai_module._log_remote_image_runtime_config_once()

    assert mock_info.call_count == 1


def test_build_vertex_messages_preserves_data_url_image_parts():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA",
                    },
                },
            ],
        }
    ]

    _, contents = _build_vertex_messages(messages)
    parts = contents[0]["parts"]

    assert any(part.get("text") == "Describe this image." for part in parts)
    inline_parts = [part for part in parts if "inlineData" in part]
    assert len(inline_parts) == 1
    assert inline_parts[0]["inlineData"]["mimeType"] == "image/png"
    assert inline_parts[0]["inlineData"]["data"] == "iVBORw0KGgoAAAANSUhEUgAAAAUA"


def test_build_vertex_messages_input_image_string_supported():
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ",
                }
            ],
        }
    ]

    _, contents = _build_vertex_messages(messages)
    parts = contents[0]["parts"]
    inline_parts = [part for part in parts if "inlineData" in part]

    assert len(inline_parts) == 1
    assert inline_parts[0]["inlineData"]["mimeType"] == "image/jpeg"
    assert inline_parts[0]["inlineData"]["data"] == "/9j/4AAQSkZJRgABAQ"


def test_build_vertex_messages_local_path_image_supported(tmp_path):
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    img = tmp_path / "sample.png"
    img.write_bytes(img_bytes)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": str(img)},
                }
            ],
        }
    ]

    _, contents = _build_vertex_messages(messages)
    inline_parts = [part for part in contents[0]["parts"] if "inlineData" in part]

    assert len(inline_parts) == 1
    assert inline_parts[0]["inlineData"]["mimeType"] == "image/png"
    assert inline_parts[0]["inlineData"]["data"] == base64.b64encode(img_bytes).decode("ascii")


def test_build_vertex_messages_file_uri_image_supported(tmp_path):
    img_bytes = b"\xff\xd8\xff" + b"\x00" * 8
    img = tmp_path / "sample.jpg"
    img.write_bytes(img_bytes)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": img.as_uri()},
                }
            ],
        }
    ]

    _, contents = _build_vertex_messages(messages)
    inline_parts = [part for part in contents[0]["parts"] if "inlineData" in part]

    assert len(inline_parts) == 1
    assert inline_parts[0]["inlineData"]["mimeType"] == "image/jpeg"
    assert inline_parts[0]["inlineData"]["data"] == base64.b64encode(img_bytes).decode("ascii")


def test_build_vertex_messages_remote_http_image_supported():
    vertex_ai_module._clear_remote_image_cache_for_tests()
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

    class _FakeResponse:
        def __init__(self):
            self.url = "https://example.com/image.png"
            self.headers = {
                "content-length": str(len(img_bytes)),
                "content-type": "image/png",
            }
            self.content = img_bytes
            self.is_redirect = False
            self.next_request = None

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield self.content

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/image.png"},
                }
            ],
        }
    ]

    with (
        patch("tools.url_safety.is_safe_url", return_value=True),
        patch("tools.website_policy.check_website_access", return_value=None),
        patch("agent.models.vertex_ai.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        stream_cm = MagicMock()
        stream_cm.__enter__.return_value = _FakeResponse()
        stream_cm.__exit__.return_value = False
        mock_client.stream.return_value = stream_cm
        mock_client_cls.return_value = mock_client

        _, contents = _build_vertex_messages(messages)

    inline_parts = [part for part in contents[0]["parts"] if "inlineData" in part]
    assert len(inline_parts) == 1
    assert inline_parts[0]["inlineData"]["mimeType"] == "image/png"
    assert inline_parts[0]["inlineData"]["data"] == base64.b64encode(img_bytes).decode("ascii")


def test_build_vertex_messages_remote_http_blocked_falls_back_to_text():
    vertex_ai_module._clear_remote_image_cache_for_tests()
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://blocked.example.com/pic.png"},
                }
            ],
        }
    ]

    with (
        patch("tools.url_safety.is_safe_url", return_value=False),
        patch("tools.website_policy.check_website_access", return_value=None),
    ):
        _, contents = _build_vertex_messages(messages)

    text_parts = [part.get("text") for part in contents[0]["parts"] if "text" in part]
    assert any("[Image URL: https://blocked.example.com/pic.png]" == t for t in text_parts)


def test_build_vertex_messages_remote_http_non_image_payload_falls_back_to_text():
    vertex_ai_module._clear_remote_image_cache_for_tests()
    bad_bytes = b"not-a-real-image-payload"

    class _FakeResponse:
        def __init__(self):
            self.url = "https://example.com/not-image.png"
            self.headers = {
                "content-length": str(len(bad_bytes)),
                "content-type": "image/png",
            }
            self.content = bad_bytes
            self.is_redirect = False
            self.next_request = None

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield self.content

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/not-image.png"},
                }
            ],
        }
    ]

    with (
        patch("tools.url_safety.is_safe_url", return_value=True),
        patch("tools.website_policy.check_website_access", return_value=None),
        patch("agent.models.vertex_ai.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        stream_cm = MagicMock()
        stream_cm.__enter__.return_value = _FakeResponse()
        stream_cm.__exit__.return_value = False
        mock_client.stream.return_value = stream_cm
        mock_client_cls.return_value = mock_client

        _, contents = _build_vertex_messages(messages)

    inline_parts = [part for part in contents[0]["parts"] if "inlineData" in part]
    assert len(inline_parts) == 0
    text_parts = [part.get("text") for part in contents[0]["parts"] if "text" in part]
    assert any("[Image URL: https://example.com/not-image.png]" == t for t in text_parts)


def test_build_vertex_messages_remote_http_uses_cache():
    vertex_ai_module._clear_remote_image_cache_for_tests()
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

    class _FakeResponse:
        def __init__(self):
            self.url = "https://example.com/cached.png"
            self.headers = {
                "content-length": str(len(img_bytes)),
                "content-type": "image/png",
            }
            self.content = img_bytes
            self.is_redirect = False
            self.next_request = None

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield self.content

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/cached.png"},
                }
            ],
        }
    ]

    with (
        patch("tools.url_safety.is_safe_url", return_value=True),
        patch("tools.website_policy.check_website_access", return_value=None),
        patch("agent.models.vertex_ai.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        stream_cm = MagicMock()
        stream_cm.__enter__.return_value = _FakeResponse()
        stream_cm.__exit__.return_value = False
        mock_client.stream.return_value = stream_cm
        mock_client_cls.return_value = mock_client

        _build_vertex_messages(messages)
        _build_vertex_messages(messages)

    assert mock_client.stream.call_count == 1


def test_vertex_response_to_openai_parses_function_calls():
    raw = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "lookup_weather",
                                "args": {"city": "SF"},
                            }
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 5,
            "totalTokenCount": 17,
        },
    }

    response = _vertex_response_to_openai(raw, "gemini-2.5-flash")

    assert response.choices[0].finish_reason == "tool_calls"
    tool_calls = response.choices[0].message.tool_calls
    assert tool_calls is not None and len(tool_calls) == 1
    assert tool_calls[0].function.name == "lookup_weather"
    assert tool_calls[0].function.arguments == '{"city":"SF"}'
    assert response.usage.total_tokens == 17


def test_vertex_response_preserves_thought_signature_in_tool_call_extra_content():
    raw = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "thoughtSignature": "sig-abc",
                            "functionCall": {
                                "name": "lookup_weather",
                                "args": {"city": "SF"},
                            },
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    response = _vertex_response_to_openai(raw, "gemini-3.1-pro-preview")
    tool_calls = response.choices[0].message.tool_calls
    assert tool_calls is not None and len(tool_calls) == 1
    assert tool_calls[0].extra_content == {"google": {"thought_signature": "sig-abc"}}


def test_vertex_response_preserves_snake_case_thought_signature():
    raw = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "thought_signature": "sig-snake",
                            "functionCall": {
                                "name": "terminal",
                                "args": {"command": "pwd"},
                                "thought_signature": "sig-snake",
                            },
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    response = _vertex_response_to_openai(raw, "gemini-3.1-pro-preview")
    tool_calls = response.choices[0].message.tool_calls
    assert tool_calls is not None and len(tool_calls) == 1
    assert tool_calls[0].extra_content == {"google": {"thought_signature": "sig-snake"}}


def test_build_vertex_messages_replays_thought_signature_for_tool_roundtrip():
    messages = [
        {"role": "user", "content": "Check gateway"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_sig_1",
                    "type": "function",
                    "extra_content": {"google": {"thought_signature": "sig-123"}},
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command":"pgrep -af hermes"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_sig_1",
            "content": '{"output":"ok"}',
        },
    ]

    _, contents = _build_vertex_messages(messages)
    assert len(contents) == 3
    model_parts = contents[1]["parts"]
    tool_response_parts = contents[2]["parts"]
    assert any(part.get("thoughtSignature") == "sig-123" for part in model_parts)
    assert any(part.get("functionResponse") for part in tool_response_parts)


def test_vertex_stream_preserves_late_signature_chunk():
    client = VertexAIClient(
        api_key="vertex-key",
        project_id="proj-test",
        region="global",
        default_model="gemini-3.1-pro-preview",
    )

    async def fake_stream_generate_content(*, model_name, payload, timeout_seconds):
        # Step 1: model starts function call (no signature yet)
        yield {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "terminal",
                                    "args": {"command": "echo hi"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
        # Step 2: signature arrives in a chunk with no new id/name/args deltas
        yield {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "thought_signature": "sig-late",
                                "functionCall": {
                                    "name": "terminal",
                                    "args": {"command": "echo hi"},
                                },
                            }
                        ]
                    }
                }
            ]
        }
        # Step 3: finish with args but no signature present in this final chunk
        yield {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "terminal",
                                    "args": {"command": "echo hi"},
                                }
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }

    client._transport.stream_generate_content = fake_stream_generate_content

    async def collect():
        chunks = []
        async for chunk in client._acreate_stream(
            model="gemini-3.1-pro-preview",
            messages=[{"role": "user", "content": "run terminal"}],
            stream=True,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())

    saw_signature_delta = False
    for chunk in chunks:
        for choice in getattr(chunk, "choices", []):
            delta = getattr(choice, "delta", None)
            for tool_delta in getattr(delta, "tool_calls", []) or []:
                if getattr(tool_delta, "extra_content", None) == {"google": {"thought_signature": "sig-late"}}:
                    saw_signature_delta = True

    assert saw_signature_delta is True

    client.close()


def test_vertex_stream_text_deltas_and_usage():
    client = VertexAIClient(
        api_key="vertex-key",
        project_id="proj-test",
        region="global",
        default_model="gemini-2.5-flash",
    )

    async def fake_stream_generate_content(*, model_name, payload, timeout_seconds):
        assert model_name == "gemini-2.5-flash"
        yield {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hel"}]},
                }
            ]
        }
        yield {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hello"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 9,
                "candidatesTokenCount": 4,
                "totalTokenCount": 13,
            },
        }

    client._transport.stream_generate_content = fake_stream_generate_content

    async def collect():
        chunks = []
        async for chunk in client._acreate_stream(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "Say hello"}],
            stream=True,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())

    assert len(chunks) == 3
    assert chunks[0].choices[0].delta.content == "Hel"
    assert chunks[1].choices[0].delta.content == "lo"
    assert chunks[1].choices[0].finish_reason == "stop"
    assert chunks[2].choices == []
    assert chunks[2].usage.total_tokens == 13

    client.close()


def test_vertex_stream_tool_args_emitted_once_on_completion():
    client = VertexAIClient(
        api_key="vertex-key",
        project_id="proj-test",
        region="global",
        default_model="gemini-2.5-flash",
    )

    async def fake_stream_generate_content(*, model_name, payload, timeout_seconds):
        yield {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "lookup_weather",
                                    "args": {"q": "wea"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
        yield {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "lookup_weather",
                                    "args": {"q": "weather"},
                                }
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }

    client._transport.stream_generate_content = fake_stream_generate_content

    async def collect():
        chunks = []
        async for chunk in client._acreate_stream(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "Use the weather tool"}],
            stream=True,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())

    emitted_arguments = ""
    finish_reasons = []
    for chunk in chunks:
        for choice in getattr(chunk, "choices", []):
            finish_reasons.append(choice.finish_reason)
            delta = getattr(choice, "delta", None)
            for tool_delta in getattr(delta, "tool_calls", []) or []:
                args = getattr(tool_delta.function, "arguments", None)
                if args:
                    emitted_arguments += args

    assert emitted_arguments == '{"q":"weather"}'
    assert "tool_calls" in finish_reasons

    client.close()
