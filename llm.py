"""LLM client wrappers for Ollama and DeepSeek."""

import json
import os
import queue
import re
import threading
import time
from typing import Any, Iterable

import httpx

OLLAMA_TIMEOUT_SECONDS = 180
OLLAMA_HEARTBEAT_SECONDS = 5

THINKING_BLOCK_RE = re.compile(
    r"<\|(?:redacted_)?think(?:ing)?\|>.*?<\|/(?:redacted_)?think(?:ing)?\|>",
    re.DOTALL | re.IGNORECASE,
)


def strip_thinking_markup(text: str) -> str:
    return THINKING_BLOCK_RE.sub("", text)


def _response_content(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return chunk.get("message", {}).get("content", "")
    message = getattr(chunk, "message", None)
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "") or ""


def _response_thinking(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return chunk.get("message", {}).get("thinking", "") or ""
    message = getattr(chunk, "message", None)
    if isinstance(message, dict):
        return message.get("thinking", "") or ""
    return getattr(message, "thinking", "") or ""


# --- Ollama ---

def ollama_chat_complete(
    *,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any],
    response_format: str | dict[str, Any] | None = None,
    think: bool = False,
) -> str:
    try:
        import ollama
    except ImportError as error:
        raise RuntimeError("Ollama Python client not available.") from error
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "options": options,
        "stream": False,
        "think": think,
        "keep_alive": "30s",
    }
    if response_format:
        kwargs["format"] = response_format
    response = ollama.Client(timeout=OLLAMA_TIMEOUT_SECONDS).chat(**kwargs)
    return strip_thinking_markup(_response_content(response))


def stream_ollama_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any],
    response_format: str | dict[str, Any] | None = None,
    think: bool = False,
    first_chunk_timeout_seconds: int = 30,
    stop_event: threading.Event | None = None,
) -> Iterable[tuple[str, str, str]]:
    """Stream from Ollama HTTP API. Yields (content_delta, full_content, think_delta)."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "options": options,
        "stream": True,
        "think": think,
        "keep_alive": "30s",
    }
    if response_format:
        payload["format"] = response_format

    content_parts: list[str] = []
    thinking_parts: list[str] = []
    visible_content = ""
    visible_thinking = ""
    timeout = httpx.Timeout(
        connect=10.0,
        read=float(max(first_chunk_timeout_seconds, OLLAMA_TIMEOUT_SECONDS)),
        write=10.0,
        pool=10.0,
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", "http://127.0.0.1:11434/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if stop_event and stop_event.is_set():
                        return
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(str(chunk["error"]))
                    thinking = _response_thinking(chunk)
                    content = _response_content(chunk)

                    think_delta = ""
                    content_delta = ""
                    if content:
                        if content_parts and content.startswith("".join(content_parts)):
                            cleaned = strip_thinking_markup(content)
                        else:
                            content_parts.append(content)
                            cleaned = strip_thinking_markup("".join(content_parts))
                        content_delta = cleaned[len(visible_content):]
                        visible_content = cleaned
                    if thinking:
                        if thinking_parts and thinking.startswith("".join(thinking_parts)):
                            full_thinking = thinking
                        else:
                            thinking_parts.append(thinking)
                            full_thinking = "".join(thinking_parts)
                        think_delta = full_thinking[len(visible_thinking):]
                        visible_thinking = full_thinking
                    if think_delta or content_delta:
                        yield content_delta, visible_content, think_delta
    except httpx.TimeoutException as error:
        raise TimeoutError(
            f"Ollama did not return tokens within {first_chunk_timeout_seconds}s."
        ) from error


# --- DeepSeek ---

def _require_deepseek_api_key() -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured.")
    return api_key


def stream_deepseek_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    think: bool = False,
    stop_event: threading.Event | None = None,
) -> Iterable[tuple[str, str, str]]:
    """Stream from DeepSeek API. Yields (content_delta, full_content, think_delta)."""
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("OpenAI SDK is not installed.") from error

    client = OpenAI(
        api_key=_require_deepseek_api_key(),
        base_url="https://api.deepseek.com",
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    request_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if think:
        request_kwargs["reasoning_effort"] = "high"
        request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    stream = client.chat.completions.create(**request_kwargs)

    content_parts: list[str] = []
    thinking_parts: list[str] = []
    visible_content = ""
    visible_thinking = ""
    try:
        for chunk in stream:
            if stop_event and stop_event.is_set():
                return
            if not chunk.choices:
                continue
            delta_obj = chunk.choices[0].delta
            content = str(getattr(delta_obj, "content", "") or "")
            thinking = str(
                getattr(delta_obj, "reasoning_content", None)
                or getattr(delta_obj, "thinking", None)
                or ""
            )

            content_delta = ""
            think_delta = ""
            if content:
                content_parts.append(content)
                full = strip_thinking_markup("".join(content_parts))
                content_delta = full[len(visible_content):]
                visible_content = full
            if thinking:
                thinking_parts.append(thinking)
                full_t = "".join(thinking_parts)
                think_delta = full_t[len(visible_thinking):]
                visible_thinking = full_t
            if content_delta or think_delta:
                yield content_delta, visible_content, think_delta
    finally:
        close_fn = getattr(stream, "close", None)
        if callable(close_fn):
            close_fn()


# --- Unified streaming with heartbeat ---

def stream_chat_with_heartbeat(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any],
    response_format: str | dict[str, Any] | None = None,
    think: bool = False,
    first_chunk_timeout_seconds: int = 30,
    stop_event: threading.Event | None = None,
) -> Iterable[tuple[str, Any]]:
    """Yields ("heartbeat", elapsed_seconds) or ("chunk", (delta, full, think_delta))."""
    output_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

    def worker() -> None:
        try:
            if provider == "deepseek":
                gen = stream_deepseek_chat(
                    model=model,
                    messages=messages,
                    temperature=float(options.get("temperature", 0.15)),
                    max_tokens=int(options.get("num_predict", 16000)),
                    think=think,
                    stop_event=stop_event,
                )
            else:
                gen = stream_ollama_chat(
                    model=model,
                    messages=messages,
                    options=options,
                    response_format=response_format,
                    think=think,
                    first_chunk_timeout_seconds=first_chunk_timeout_seconds,
                    stop_event=stop_event,
                )
            for item in gen:
                if stop_event and stop_event.is_set():
                    return
                output_queue.put(("chunk", item))
            output_queue.put(("done", None))
        except Exception as error:
            output_queue.put(("error", error))

    threading.Thread(target=worker, daemon=True).start()
    started_at = time.monotonic()
    seen_chunk = False
    while True:
        if stop_event and stop_event.is_set():
            return
        try:
            event, payload = output_queue.get(timeout=OLLAMA_HEARTBEAT_SECONDS)
        except queue.Empty:
            elapsed = int(time.monotonic() - started_at)
            if not seen_chunk and elapsed >= first_chunk_timeout_seconds:
                raise TimeoutError(
                    f"Model did not return the first token within {first_chunk_timeout_seconds}s."
                )
            yield "heartbeat", elapsed
            continue
        if event == "chunk":
            seen_chunk = True
            yield event, payload
        elif event == "done":
            return
        elif event == "error":
            raise payload
