# -*- coding: utf-8 -*-
"""
agent_prompt_helpers package
============================

This package groups small, focused helper modules used by AgentPrompt.
Each file has a single responsibility:
- json_parser: safe extraction of JSON from raw LLM text.
- field_normalizer: validation/normalization of enum fields.
- config_loader: convert JSON 'fields' into Python dicts (enums, defaults, etc.).
- schema_map: mapping from field_id to result_key used in JSON.
- compose_texts: build system/user messages for chooser mode.
"""
