from __future__ import annotations

import json
import os
from urllib import error, request


def normalize_api_type(api_type: str | None, base_url: str) -> str:
    if api_type:
        normalized = api_type.strip().lower()
        if normalized in {"chat", "chat_completions", "chat-completions"}:
            return "chat_completions"
        if normalized in {"responses", "response"}:
            return "responses"

    normalized_base_url = base_url.rstrip("/").lower()
    if normalized_base_url.endswith("/responses"):
        return "responses"
    return "chat_completions"


def build_endpoint(base_url: str, api_type: str) -> str:
    normalized_base_url = base_url.rstrip("/")
    if api_type == "responses":
        if normalized_base_url.endswith("/responses"):
            return normalized_base_url
        return f"{normalized_base_url}/responses"

    if normalized_base_url.endswith("/chat/completions"):
        return normalized_base_url
    return f"{normalized_base_url}/chat/completions"


def build_payload(prompt: str, *, model: str, temperature: float, api_type: str) -> dict[str, object]:
    if api_type == "responses":
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


def extract_response_text(data: dict[str, object], response_body: str, api_type: str) -> str:
    if api_type == "responses":
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict) or part.get("type") != "output_text":
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()

        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        raise RuntimeError(f"Unexpected LLM response payload: {response_body}")

    try:
        choices = data["choices"]
        if not isinstance(choices, list) or not choices:
            raise KeyError("choices")
        message = choices[0]["message"]
        if not isinstance(message, dict):
            raise KeyError("message")
        content = message["content"]
        if not isinstance(content, str):
            raise TypeError("content")
        return content.strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM response payload: {response_body}") from exc


def llm_completion(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    api_type: str | None = None,
    temperature: float = 0.7,
    timeout: int = 120,
) -> str:
    resolved_api_type = normalize_api_type(api_type, base_url)
    endpoint = build_endpoint(base_url, resolved_api_type)
    payload = build_payload(prompt, model=model, temperature=temperature, api_type=resolved_api_type)
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
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with status {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

    data = json.loads(response_body)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected LLM response payload: {response_body}")
    return extract_response_text(data, response_body, resolved_api_type)


def test_llm_connection(
    *,
    model: str,
    api_key: str,
    base_url: str,
    api_type: str | None = None,
    timeout: int = 20,
) -> dict[str, object]:
    resolved_api_type = normalize_api_type(api_type, base_url)
    endpoint = build_endpoint(base_url, resolved_api_type)
    payload = build_payload("ping", model=model, temperature=0, api_type=resolved_api_type)
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
    extract_response_text(data, response_body, resolved_api_type)

    return {
        "ok": True,
        "endpoint": endpoint,
        "model": model,
        "apiType": resolved_api_type,
        "status": int(status_code),
    }


def read_api_config(
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    api_type: str | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    resolved_api_key = api_key or os.getenv("BAIBAIAIGC_API_KEY") or os.getenv("OPENAI_API_KEY")
    resolved_model = model or os.getenv("BAIBAIAIGC_MODEL")
    resolved_base_url = (
        base_url
        or os.getenv("BAIBAIAIGC_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )
    resolved_api_type = api_type or os.getenv("BAIBAIAIGC_API_TYPE")
    return resolved_api_key, resolved_model, resolved_base_url, resolved_api_type


def chat_completion(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.7,
    timeout: int = 120,
) -> str:
    return llm_completion(
        prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        api_type="chat_completions",
        temperature=temperature,
        timeout=timeout,
    )