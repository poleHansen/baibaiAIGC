from __future__ import annotations

import json
import os
from urllib import error, request


def normalize_api_mode(api_mode: str | None) -> str:
    normalized = str(api_mode or "responses").strip().lower()
    if normalized in {"responses", "response", "/v1/responses"}:
        return "responses"
    if normalized in {"chat-completions", "chat_completions", "chat/completions", "/v1/chat/completions"}:
        return "chat-completions"
    raise ValueError(f"Unsupported API mode: {api_mode}")


def build_chat_endpoint(base_url: str) -> str:
    normalized_base_url = base_url.rstrip("/")
    if normalized_base_url.endswith("/chat/completions"):
        return normalized_base_url
    return f"{normalized_base_url}/chat/completions"


def build_responses_endpoint(base_url: str) -> str:
    normalized_base_url = base_url.rstrip("/")
    if normalized_base_url.endswith("/responses"):
        return normalized_base_url
    return f"{normalized_base_url}/responses"


def build_endpoint(base_url: str, api_mode: str | None) -> str:
    resolved_mode = normalize_api_mode(api_mode)
    if resolved_mode == "responses":
        return build_responses_endpoint(base_url)
    return build_chat_endpoint(base_url)


def _build_payload(prompt: str, model: str, temperature: float, api_mode: str) -> dict[str, object]:
    if api_mode == "responses":
        return {
            "model": model,
            "input": prompt,
            "temperature": temperature,
        }
    return {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }


def _extract_responses_text(data: dict[str, object], response_body: str) -> str:
    output = data.get("output")
    if isinstance(output, list):
        text_fragments: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"}:
                    text_value = part.get("text")
                    if isinstance(text_value, str) and text_value.strip():
                        text_fragments.append(text_value)
        if text_fragments:
            return "\n".join(fragment.strip() for fragment in text_fragments if fragment.strip()).strip()

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    raise RuntimeError(f"Unexpected LLM response payload: {response_body}")


def _extract_text(data: dict[str, object], response_body: str, api_mode: str) -> str:
    if api_mode == "responses":
        return _extract_responses_text(data, response_body)
    try:
        return str(data["choices"][0]["message"]["content"]).strip()  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM response payload: {response_body}") from exc


def _request_llm(
    *,
    prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    timeout: int,
    api_mode: str | None,
) -> tuple[str, str, int]:
    resolved_mode = normalize_api_mode(api_mode)
    endpoint = build_endpoint(base_url, resolved_mode)
    payload = _build_payload(prompt, model, temperature, resolved_mode)
    body = json.dumps(payload).encode("utf-8")

    http_request = request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            status_code = getattr(response, "status", 200)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with status {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

    data = json.loads(response_body)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected LLM response payload: {response_body}")

    text = _extract_text(data, response_body, resolved_mode)
    return text, endpoint, int(status_code)


def chat_completion(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    api_mode: str | None = None,
    temperature: float = 0.7,
    timeout: int = 120,
) -> str:
    text, _, _ = _request_llm(
        prompt=prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
        api_mode=api_mode,
    )
    return text


def test_chat_connection(
    *,
    model: str,
    api_key: str,
    base_url: str,
    api_mode: str | None = None,
    timeout: int = 20,
) -> dict[str, object]:
    _, endpoint, status_code = _request_llm(
        prompt="ping",
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=timeout,
        api_mode=api_mode,
    )

    return {
        "ok": True,
        "endpoint": endpoint,
        "model": model,
        "status": int(status_code),
    }


def read_api_config(
    api_key: str | None,
    model: str | None,
    base_url: str | None,
) -> tuple[str | None, str | None, str | None]:
    resolved_api_key = api_key or os.getenv("BAIBAIAIGC_API_KEY") or os.getenv("OPENAI_API_KEY")
    resolved_model = model or os.getenv("BAIBAIAIGC_MODEL")
    resolved_base_url = (
        base_url
        or os.getenv("BAIBAIAIGC_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )
    return resolved_api_key, resolved_model, resolved_base_url