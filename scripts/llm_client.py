from __future__ import annotations

import json
import os
from urllib import error, request


DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "User-Agent": "curl/8.7.1",
}
ERROR_BODY_PREVIEW_LIMIT = 240


class LLMClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: str,
        retriable: bool = False,
        provider_status: int | None = None,
        api_type: str | None = None,
        detail: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retriable = retriable
        self.provider_status = provider_status
        self.api_type = api_type
        self.detail = detail


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


def build_headers(api_key: str) -> dict[str, str]:
    return {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {api_key}",
    }


def _preview_response_body(response_body: str) -> str:
    compact = " ".join(str(response_body).split())
    if len(compact) <= ERROR_BODY_PREVIEW_LIMIT:
        return compact
    return f"{compact[:ERROR_BODY_PREVIEW_LIMIT]}..."


def _raise_http_error(exc: error.HTTPError, api_type: str | None) -> None:
    detail = exc.read().decode("utf-8", errors="replace")
    status_code = int(exc.code)
    preview = _preview_response_body(detail)
    raise LLMClientError(
        f"LLM request failed with status {status_code}: {preview}",
        code="provider_http_error",
        stage="llm_http",
        retriable=status_code >= 500 or status_code == 429,
        provider_status=status_code,
        api_type=api_type,
        detail=preview,
    ) from exc


def _load_json_response(
    response_body: str,
    *,
    status_code: int,
    content_type: str,
    api_type: str,
) -> dict[str, object]:
    preview = _preview_response_body(response_body)
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        normalized_content_type = content_type.lower()
        code = "provider_non_json_response" if "json" not in normalized_content_type else "provider_invalid_json"
        raise LLMClientError(
            f"LLM returned invalid JSON payload (status {status_code}, content-type {content_type or 'unknown'}): {preview}",
            code=code,
            stage="llm_parse",
            retriable=True,
            provider_status=status_code,
            api_type=api_type,
            detail=preview,
        ) from exc
    if not isinstance(data, dict):
        raise LLMClientError(
            f"Unexpected LLM response payload: {preview}",
            code="provider_unexpected_schema",
            stage="llm_schema",
            retriable=False,
            provider_status=status_code,
            api_type=api_type,
            detail=preview,
        )
    return data


def _join_text_parts(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part).strip()


def _extract_text_candidate(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_text_candidate(item)
            if text:
                parts.append(text)
        return _join_text_parts(parts)
    if not isinstance(value, dict):
        return ""

    direct_text = value.get("text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    nested_text = value.get("content")
    if isinstance(nested_text, str) and nested_text.strip():
        return nested_text.strip()
    if isinstance(nested_text, list):
        nested_parts = [_extract_text_candidate(item) for item in nested_text]
        return _join_text_parts(nested_parts)

    return ""


def extract_response_text(data: dict[str, object], response_body: str, api_type: str) -> str:
    preview = _preview_response_body(response_body)
    if api_type == "responses":
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                text = _extract_text_candidate(content)
                if text:
                    return text

        output_text = data.get("output_text")
        text = _extract_text_candidate(output_text)
        if text:
            return text

        raise LLMClientError(
            f"Unexpected LLM response payload: {preview}",
            code="provider_unexpected_schema",
            stage="llm_schema",
            retriable=False,
            api_type=api_type,
            detail=preview,
        )

    try:
        choices = data["choices"]
        if not isinstance(choices, list) or not choices:
            raise KeyError("choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError("choice")

        message = choice.get("message")
        if isinstance(message, dict):
            text = _extract_text_candidate(message.get("content"))
            if text:
                return text

        text = _extract_text_candidate(choice.get("text"))
        if text:
            return text

        raise KeyError("message.content")
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMClientError(
            f"Unexpected LLM response payload: {preview}",
            code="provider_unexpected_schema",
            stage="llm_schema",
            retriable=False,
            api_type=api_type,
            detail=preview,
        ) from exc


def _request_llm_json(
    payload: dict[str, object],
    *,
    api_key: str,
    base_url: str,
    api_type: str | None,
    timeout: int,
) -> tuple[dict[str, object], int, str, str, str]:
    resolved_api_type = normalize_api_type(api_type, base_url)
    endpoint = build_endpoint(base_url, resolved_api_type)
    body = json.dumps(payload).encode("utf-8")

    http_request = request.Request(
        endpoint,
        data=body,
        headers=build_headers(api_key),
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type", "") or "")
    except error.HTTPError as exc:
        _raise_http_error(exc, resolved_api_type)
    except error.URLError as exc:
        raise LLMClientError(
            f"LLM request failed: {exc.reason}",
            code="provider_network_error",
            stage="llm_http",
            retriable=True,
            api_type=resolved_api_type,
            detail=str(exc.reason),
        ) from exc

    return (
        _load_json_response(
            response_body,
            status_code=status_code,
            content_type=content_type,
            api_type=resolved_api_type,
        ),
        status_code,
        endpoint,
        resolved_api_type,
        response_body,
    )


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
    payload = build_payload(
        prompt,
        model=model,
        temperature=temperature,
        api_type=normalize_api_type(api_type, base_url),
    )
    data, _, _, resolved_api_type, response_body = _request_llm_json(
        payload,
        api_key=api_key,
        base_url=base_url,
        api_type=api_type,
        timeout=timeout,
    )
    return extract_response_text(data, response_body, resolved_api_type)


def test_llm_connection(
    *,
    model: str,
    api_key: str,
    base_url: str,
    api_type: str | None = None,
    timeout: int = 20,
) -> dict[str, object]:
    payload = build_payload(
        "ping",
        model=model,
        temperature=0,
        api_type=normalize_api_type(api_type, base_url),
    )
    data, status_code, endpoint, resolved_api_type, response_body = _request_llm_json(
        payload,
        api_key=api_key,
        base_url=base_url,
        api_type=api_type,
        timeout=timeout,
    )
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