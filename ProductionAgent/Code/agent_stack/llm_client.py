# ragstream/orchestration/llm_client.py
# -*- coding: utf-8 -*-
"""
LLMClient — thin wrapper around an LLM provider.

Current implementation:
- Uses OpenAI Python client v1 (OpenAI() + client.chat.completions.create).
- Reads OPENAI_API_KEY from environment (or optional api_key in __init__).
- Keeps backward compatibility for old callers:
    * default return = raw content string
- Supports optional metadata return for cache/token inspection:
    * return_metadata=True -> {"content": "...", "usage": {...}}

Added:
- Responses API path for A4 / reasoning-model calls.
- Metadata extraction for:
    * model name
    * status
    * incomplete reason
    * input tokens
    * cached input tokens
    * output tokens
    * reasoning tokens

CLI logging:
- Always logs model name, total input tokens, cached input tokens, and output tokens
  for both chat() and responses().
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import os

from app_logging.agent_logger import SimpleLogger

try:
    from openai import OpenAI  # type: ignore[import]
except ImportError:  # pragma: no cover - import guard
    OpenAI = None  # type: ignore[assignment]

JsonDict = Dict[str, Any]


class LLMClient:
    """
    Neutral LLM gateway.

    Default behavior stays backward compatible:
    - chat() returns raw content string

    Optional metadata:
    - chat(..., return_metadata=True)
    - responses(..., return_metadata=True)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self._client: Optional[OpenAI] = None  # type: ignore[type-arg]

        if OpenAI is None:
            SimpleLogger.info(
                "LLMClient: 'openai' v1 client not installed. Any LLM call will fail until you "
                "install it (e.g. 'pip install openai')."
            )
            return

        if not key:
            SimpleLogger.info(
                "LLMClient: OPENAI_API_KEY not set. Any LLM call will fail until you set it."
            )
            return

        try:
            self._client = OpenAI(api_key=key)
            SimpleLogger.info("LLMClient: OpenAI client initialised (v1 API).")
        except Exception as exc:
            SimpleLogger.error(f"LLMClient: failed to initialise OpenAI client: {exc!r}")
            self._client = None

    def chat(
        self,
        *,
        messages: List[Dict[str, str]],
        model_name: str,
        temperature: float,
        max_output_tokens: int,
        response_format: Dict[str, Any] | None = None,
        reasoning_effort: Optional[str] = None,
        return_metadata: bool = False,
        prompt_cache_key: Optional[str] = None,
        prompt_cache_retention: Optional[str] = None,
    ) -> Union[str, JsonDict]:
        """
        Thin wrapper over OpenAI chat.completions.

        Notes:
        - Uses max_completion_tokens (new API) instead of max_tokens.
        - For gpt-5* reasoning models, temperature is omitted.
        - Prompt caching for recent models is automatic on the provider side.
        """
        if self._client is None:
            raise RuntimeError("LLMClient: OpenAI client is not initialised")

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_completion_tokens": int(max_output_tokens),
        }

        if response_format is not None:
            kwargs["response_format"] = response_format

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        if temperature is not None and not str(model_name).startswith("gpt-5"):
            kwargs["temperature"] = float(temperature)

        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key  # Added: stable cache-routing key per prompt family.

      # if prompt_cache_retention:
           # kwargs["prompt_cache_retention"] = prompt_cache_retention  # Added: explicit retention policy for prompt cache.

        resp = self._client.chat.completions.create(**kwargs)

        content = resp.choices[0].message.content
        content_text = content if isinstance(content, str) else str(content or "")

        usage = self._extract_chat_usage(resp)
        actual_model_name = str(getattr(resp, "model", "") or model_name)
        self._log_chat_usage(actual_model_name, usage)

        if not return_metadata:
            return content_text

        return {
            "content": content_text,
            "usage": usage,
            "model_name": actual_model_name,
            "status": "",
            "incomplete_reason": "",
        }

    def responses(
        self,
        *,
        messages: List[Dict[str, str]],
        model_name: str,
        max_output_tokens: int,
        reasoning_effort: Optional[str] = None,
        return_metadata: bool = False,
        prompt_cache_key: Optional[str] = None,
        prompt_cache_retention: Optional[str] = None,
    ) -> Union[str, JsonDict]:
        """
        Responses API path used for A4 / reasoning-style calls.

        Design:
        - First SYSTEM message becomes `instructions`.
        - Remaining messages are collapsed into one text input string.
        - reasoning_effort is explicitly controlled here.

        Important fix:
        - If the composed prompt has no non-system message, Responses API still
          requires `input`.
        - In that case we move the instructions text into `input` and clear
          `instructions`.
        """
        if self._client is None:
            raise RuntimeError("LLMClient: OpenAI client is not initialised")

        instructions = ""
        input_parts: List[str] = []

        for message in messages:
            role = str(message.get("role", "") or "").strip().lower()
            content = str(message.get("content", "") or "")

            if role == "system" and not instructions:
                instructions = content
            else:
                if content:
                    input_parts.append(content)

        input_text = "\n\n".join(part for part in input_parts if part).strip()

        # Fix for "missing_required_parameter":
        # if everything is inside the system message, move it into input.
        if not input_text and instructions:
            input_text = instructions
            instructions = ""

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "input": input_text,
            "max_output_tokens": int(max_output_tokens),
        }

        if reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        if instructions:
            kwargs["instructions"] = instructions

        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key  # Added: stable cache-routing key per prompt family.

       # if prompt_cache_retention:
         #   kwargs["prompt_cache_retention"] = prompt_cache_retention  # Added: explicit retention policy for prompt cache.

        resp = self._client.responses.create(**kwargs)

        content_text = self._extract_response_text(resp)
        usage = self._extract_response_usage(resp)
        status = self._extract_response_status(resp)
        incomplete_reason = self._extract_response_incomplete_reason(resp)
        actual_model_name = str(getattr(resp, "model", "") or model_name)

        self._log_response_usage(
            actual_model_name=actual_model_name,
            usage=usage,
            status=status,
            incomplete_reason=incomplete_reason,
        )

        if not return_metadata:
            return content_text

        return {
            "content": content_text,
            "usage": usage,
            "model_name": actual_model_name,
            "status": status,
            "incomplete_reason": incomplete_reason,
        }

    @staticmethod
    def _extract_chat_usage(resp: Any) -> JsonDict:
        """
        Extract token usage including cached tokens when the provider returns it.
        """
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is None:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
            }

        prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage_obj, "total_tokens", 0) or 0)

        prompt_tokens_details = getattr(usage_obj, "prompt_tokens_details", None)
        cached_tokens = 0
        if prompt_tokens_details is not None:
            cached_tokens = int(getattr(prompt_tokens_details, "cached_tokens", 0) or 0)

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": cached_tokens,
        }

    @staticmethod
    def _extract_response_text(resp: Any) -> str:
        """
        Extract visible text from a Responses API object.
        """
        output_text = getattr(resp, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        output = getattr(resp, "output", None)
        if not isinstance(output, list):
            return ""

        parts: List[str] = []

        for item in output:
            item_type = str(getattr(item, "type", "") or "")
            if item_type != "message":
                continue

            content_list = getattr(item, "content", None)
            if not isinstance(content_list, list):
                continue

            for content_item in content_list:
                content_type = str(getattr(content_item, "type", "") or "")
                if content_type in ("output_text", "text"):
                    text = getattr(content_item, "text", None)
                    if isinstance(text, str) and text:
                        parts.append(text)

        return "\n".join(parts).strip()

    @staticmethod
    def _extract_response_usage(resp: Any) -> JsonDict:
        """
        Extract token usage from a Responses API object.
        """
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is None:
            return {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
            }

        input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage_obj, "total_tokens", 0) or 0)

        input_tokens_details = getattr(usage_obj, "input_tokens_details", None)
        cached_input_tokens = 0
        if input_tokens_details is not None:
            cached_input_tokens = int(getattr(input_tokens_details, "cached_tokens", 0) or 0)

        output_tokens_details = getattr(usage_obj, "output_tokens_details", None)
        reasoning_tokens = 0
        if output_tokens_details is not None:
            reasoning_tokens = int(getattr(output_tokens_details, "reasoning_tokens", 0) or 0)

        return {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _extract_response_status(resp: Any) -> str:
        return str(getattr(resp, "status", "") or "")

    @staticmethod
    def _extract_response_incomplete_reason(resp: Any) -> str:
        incomplete_details = getattr(resp, "incomplete_details", None)
        if incomplete_details is None:
            return ""
        return str(getattr(incomplete_details, "reason", "") or "")

    @staticmethod
    def _log_chat_usage(actual_model_name: str, usage: JsonDict) -> None:
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        cached_tokens = int(usage.get("cached_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        SimpleLogger.info(
            f"LLMClient.chat | model={actual_model_name} | "
            f"input={prompt_tokens} | cached_input={cached_tokens} | output={completion_tokens}"
        )

    @staticmethod
    def _log_response_usage(
        *,
        actual_model_name: str,
        usage: JsonDict,
        status: str,
        incomplete_reason: str,
    ) -> None:
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        cached_input_tokens = int(usage.get("cached_input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)

        SimpleLogger.info(
            f"LLMClient.responses | model={actual_model_name} | "
            f"input={input_tokens} | cached_input={cached_input_tokens} | output={output_tokens}"
        )

        if status:
            SimpleLogger.info(f"LLMClient.responses | status={status}")

        if incomplete_reason:
            SimpleLogger.warning(f"LLMClient.responses | incomplete_reason={incomplete_reason}")