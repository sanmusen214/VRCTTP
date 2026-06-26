from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

import requests

from core.module import ParamType
from core.packet import (
    KEY_TARGET_LANG,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    MessagePacket,
)
from modules.translation.base import BasePacketConsumerModule

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
_REQUEST_TIMEOUT = (5, 60)
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _b64_encode_json(obj: Any) -> str:
    return base64.b64encode(
        json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")


def _b64_encode_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_decode_text(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    try:
        return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")
    except Exception:
        logger.warning("Invalid base64 config value, using raw text as fallback")
        return value


def _resolve_env_placeholders(text: str) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        value = os.environ.get(key)
        if value is None:
            logger.warning("Environment variable '%s' is not set", key)
            return match.group(0)
        return value

    return _ENV_VAR_PATTERN.sub(replace, text)


def _replace_original_placeholder(payload_text: str, original: str) -> str:
    escaped_original = json.dumps(original, ensure_ascii=False)[1:-1]
    return payload_text.replace("%{original}", escaped_original)


def _default_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer ${llm_api_key}",
        "Content-Type": "application/json",
    }


def _default_payload_text() -> str:
    payload = {
        "model": "doubao-seed-1-8-251228",
        "thinking": {"type": "disabled"},
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You are a skilled translator. Translate the following "
                            "text and return only the translation result, with no "
                            "explanation:\n%{original}"
                        ),
                    },
                ],
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


class LLMOpenAIAPICall(BasePacketConsumerModule):
    """Generic LLM HTTP JSON translation module."""

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "text_original", "must_have": True, "description": "Upstream recognized text"},
        ]

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "text_translated", "must_have": True, "description": "LLM translation result"},
            {"name": "target_lang", "must_have": True, "description": "Configured target language marker"},
        ]

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {
                "name": "target_language",
                "type": ParamType.LanguageCode,
                "default": "please_fill_target_language",
                "required": True,
                "description": "Target language marker for downstream modules. Please fill it yourself, preferably with underscores instead of spaces.",
                "selectable": None,
            },
            {
                "name": "api_url",
                "type": ParamType.String,
                "default": _DEFAULT_API_URL,
                "required": True,
                "description": "LLM API endpoint URL.",
                "selectable": None,
            },
            {
                "name": "headers_b64",
                "type": ParamType.HeaderPairsB64,
                "default": _b64_encode_json(_default_headers()),
                "required": True,
                "description": "HTTP headers. GUI edits plain key/value pairs; config stores base64(JSON object). Use ${llm_api_key} for the environment variable.",
                "selectable": None,
            },
            {
                "name": "payload_b64",
                "type": ParamType.JsonTextB64,
                "default": _b64_encode_text(_default_payload_text()),
                "required": True,
                "description": "JSON request payload. GUI edits plain JSON; config stores base64 text. Use %{original} for upstream text.",
                "selectable": None,
            },
        ]

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._target_language = config.get("target_language", "please_fill_target_language")
        self._api_url = config.get("api_url", _DEFAULT_API_URL)
        self._headers_b64 = config.get("headers_b64", _b64_encode_json(_default_headers()))
        self._payload_b64 = config.get("payload_b64", _b64_encode_text(_default_payload_text()))
        self._session = requests.Session()

    def on_after_stop(self) -> None:
        self._session.close()

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        text = packet.get(KEY_TEXT_ORIGINAL, "")
        if not isinstance(text, str) or not text.strip():
            return [packet]
        if packet.is_partial:
            return [packet]

        translated = self._translate(text.strip())
        out = packet.clone()
        out.set(KEY_TEXT_TRANSLATED, translated)
        out.set(KEY_TARGET_LANG, self._target_language)
        if translated:
            logger.info("[%s] LLM translation: %s -> %s", self.module_id, text[:50], translated[:50])
        return [out]

    def _translate(self, original: str) -> str:
        try:
            headers = self._make_headers()
            payload = self._make_payload(original)
        except ValueError as exc:
            logger.error("[%s] LLM request config error: %s", self.module_id, exc)
            return ""

        try:
            logger.info("[%s] Sending LLM translation request: %s", self.module_id, original[:80])
            response = self._session.post(
                self._api_url,
                headers=headers,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.error("[%s] LLM translation request failed: %s", self.module_id, exc)
            return ""
        except ValueError:
            logger.exception("[%s] LLM response is not valid JSON", self.module_id)
            return ""

        translated = self._extract_text(data).strip()
        if not translated:
            logger.warning("[%s] LLM response did not contain extractable text", self.module_id)
        return translated

    def _make_headers(self) -> dict[str, str]:
        raw = _b64_decode_text(self._headers_b64, json.dumps(_default_headers()))
        raw = _resolve_env_placeholders(raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"headers_b64 must decode to a JSON object: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("headers_b64 must decode to a JSON object")
        return {str(key): str(value) for key, value in data.items() if str(key).strip()}

    def _make_payload(self, original: str) -> dict:
        raw = _b64_decode_text(self._payload_b64, _default_payload_text())
        raw = _resolve_env_placeholders(raw)
        raw = _replace_original_placeholder(raw, original)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"payload_b64 must decode to valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("payload_b64 must decode to a JSON object")
        return data

    def _extract_text(self, data: Any) -> str:
        if isinstance(data, dict):
            output_text = data.get("output_text")
            if isinstance(output_text, str):
                return output_text

            choices = data.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    text = self._extract_choice_text(choice)
                    if text:
                        return text

            output = data.get("output")
            if isinstance(output, list):
                text = self._extract_text_fragments(output)
                if text:
                    return text

            for key in ("text", "translation", "translated_text", "result"):
                value = data.get(key)
                if isinstance(value, str):
                    return value
        return ""

    def _extract_choice_text(self, choice: Any) -> str:
        if not isinstance(choice, dict):
            return ""
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return self._extract_text_fragments(content)
        text = choice.get("text")
        return text if isinstance(text, str) else ""

    def _extract_text_fragments(self, value: Any) -> str:
        fragments: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                text = node.get("text")
                if isinstance(text, str):
                    fragments.append(text)
                for nested_key in ("content", "output", "message"):
                    nested = node.get(nested_key)
                    if nested is not None:
                        walk(nested)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        return "".join(fragments)
