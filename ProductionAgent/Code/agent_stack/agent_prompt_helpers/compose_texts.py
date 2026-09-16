# ragstream/orchestration/agent_prompt_helpers/compose_texts.py
# -*- coding: utf-8 -*-
"""
compose_texts
=============

Neutral text render helpers for AgentPrompt.

Rule:
- No agent-specific visible wording is invented here.
- Visible prompt wording must come from JSON or from agent-prepared runtime text.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple


def _stringify_for_prompt(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

    return str(value)


def _build_decision_targets_system_text(
    decision_targets: List[Dict[str, Any]],
    result_keys: Dict[str, str],
    enums: Dict[str, List[str]],
    option_labels: Dict[str, Dict[str, str]],
    option_descriptions: Dict[str, Dict[str, str]],
    active_fields: Optional[List[str]] = None,
) -> str:
    lines: List[str] = []

    if active_fields is None:
        active_set = None
    else:
        active_set = set(active_fields)

    for target in decision_targets or []:
        field_id = target.get("id")
        if not field_id:
            continue
        if active_set is not None and field_id not in active_set:
            continue

        label = target.get("label", field_id)
        result_key = result_keys.get(field_id, field_id)

        min_selected = int(target.get("min_selected", 1))
        max_selected = int(target.get("max_selected", 1))
        allow_null = bool(target.get("allow_null", False))

        lines.append(f"Field '{label}' (JSON key: '{result_key}')")

        if max_selected > 1 and allow_null:
            lines.append(
                f"- Select between {min_selected} and {max_selected} option ids, "
                "or JSON null when the field is absent."
            )
        elif max_selected > 1:
            lines.append(f"- Select between {min_selected} and {max_selected} option ids.")
        elif allow_null:
            lines.append("- Select exactly one option id, or JSON null when no safe selection exists.")
        else:
            lines.append("- Select exactly one option id.")

        for opt_id in enums.get(field_id, []):
            opt_label = (option_labels.get(field_id, {}).get(opt_id) or "").strip()
            opt_desc = (option_descriptions.get(field_id, {}).get(opt_id) or "").strip()

            if opt_label and opt_desc:
                lines.append(f"  * {opt_id}: {opt_label} — {opt_desc}")
            elif opt_label:
                lines.append(f"  * {opt_id}: {opt_label}")
            elif opt_desc:
                lines.append(f"  * {opt_id}: {opt_desc}")
            else:
                lines.append(f"  * {opt_id}")

        lines.append("")

    return "\n".join(lines).strip()


def build_system_text(
    static_prompt: Dict[str, Any],
    agent_name: str,
    version: str,
    decision_targets: Optional[List[Dict[str, Any]]] = None,
    result_keys: Optional[Dict[str, str]] = None,
    enums: Optional[Dict[str, List[str]]] = None,
    option_labels: Optional[Dict[str, Dict[str, str]]] = None,
    option_descriptions: Optional[Dict[str, Dict[str, str]]] = None,
    active_fields: Optional[List[str]] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    dynamic_bindings: Optional[List[Dict[str, Any]]] = None,
    elements_order: Optional[List[str]] = None,
) -> Tuple[str, Set[str]]:
    """
    Build the SYSTEM message content for the LLM.

    Important A4-compatible rule:
    - preamble is always first if present,
    - elements_order may then inject selected dynamic bindings directly into SYSTEM,
    - any dynamic binding moved into SYSTEM is removed from USER,
    - old behavior remains when elements_order is absent.
    """
    input_payload = input_payload or {}
    dynamic_bindings = dynamic_bindings or []
    elements_order = elements_order or []

    lines: List[str] = []
    consumed_binding_ids: Set[str] = set()

    preamble_text = _stringify_for_prompt(static_prompt.get("preamble", ""))
    if preamble_text:
        lines.append(preamble_text)
        lines.append("")

    remaining_static_keys = [key for key in static_prompt.keys() if str(key).strip().lower() != "preamble"]
    binding_by_id: Dict[str, Dict[str, Any]] = {
        str(binding.get("id", "")).strip(): binding
        for binding in dynamic_bindings
        if str(binding.get("id", "")).strip()
    }

    decision_targets_text = _build_decision_targets_system_text(
        decision_targets=decision_targets or [],
        result_keys=result_keys or {},
        enums=enums or {},
        option_labels=option_labels or {},
        option_descriptions=option_descriptions or {},
        active_fields=active_fields,
    )

    rendered_static_keys: Set[str] = set()
    rendered_config_decision_targets = False

    # New optional ordered render path.
    for raw_item in elements_order:
        item = str(raw_item or "").strip()
        if not item:
            continue

        normalized_item = item[3:] if item.lower().startswith("id:") else item

        if normalized_item in binding_by_id:
            binding = binding_by_id[normalized_item]
            if binding.get("visible_in_prompt", True):
                prompt_text = (binding.get("prompt_text") or "").strip()
                if prompt_text:
                    lines.append(prompt_text)

                rendered = _stringify_for_prompt(input_payload.get(normalized_item, ""))
                if rendered:
                    lines.append(rendered)

                lines.append("")
            consumed_binding_ids.add(normalized_item)
            continue

        if normalized_item == "decision_targets":
            runtime_rendered = _stringify_for_prompt(input_payload.get("decision_targets", ""))
            if runtime_rendered:
                lines.append("## Decision Targets")
                lines.append(runtime_rendered)
                lines.append("")
                consumed_binding_ids.add("decision_targets")
            elif decision_targets_text and not rendered_config_decision_targets:
                lines.append("## Decision Targets")
                lines.append(decision_targets_text)
                lines.append("")
                rendered_config_decision_targets = True
            continue

        for static_key in remaining_static_keys:
            if static_key == normalized_item and static_key not in rendered_static_keys:
                text = _stringify_for_prompt(static_prompt.get(static_key, ""))
                if text:
                    lines.append(f"## {static_key}")
                    lines.append(text)
                    lines.append("")
                rendered_static_keys.add(static_key)
                break

    # Backward-compatible default remainder for static prompt keys.
    for static_key in remaining_static_keys:
        if static_key in rendered_static_keys:
            continue
        text = _stringify_for_prompt(static_prompt.get(static_key, ""))
        if not text:
            continue
        lines.append(f"## {static_key}")
        lines.append(text)
        lines.append("")

    # Backward-compatible default remainder for config-owned decision targets.
    if decision_targets_text and not rendered_config_decision_targets:
        lines.append("## Decision Targets")
        lines.append(decision_targets_text)
        lines.append("")

    return "\n".join(lines).strip(), consumed_binding_ids


def _build_user_text_from_dynamic_bindings(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    lines: List[str] = []
    consumed_binding_ids = consumed_binding_ids or set()

    for binding in dynamic_bindings:
        if not binding.get("visible_in_prompt", True):
            continue

        binding_id = str(binding.get("id", "") or "").strip()
        if not binding_id:
            continue
        if binding_id in consumed_binding_ids:
            continue

        prompt_text = (binding.get("prompt_text") or "").strip()
        value = input_payload.get(binding_id, "")

        if prompt_text:
            lines.append(prompt_text)

        rendered = _stringify_for_prompt(value)
        if rendered:
            lines.append(rendered)

        lines.append("")

    return "\n".join(lines).strip()


def build_user_text_for_selector(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    return _build_user_text_from_dynamic_bindings(
        input_payload=input_payload,
        dynamic_bindings=dynamic_bindings,
        consumed_binding_ids=consumed_binding_ids,
    )


def build_user_text_for_classifier(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    return _build_user_text_from_dynamic_bindings(
        input_payload=input_payload,
        dynamic_bindings=dynamic_bindings,
        consumed_binding_ids=consumed_binding_ids,
    )


def build_user_text_for_synthesizer(
    input_payload: Dict[str, Any],
    dynamic_bindings: List[Dict[str, Any]],
    consumed_binding_ids: Optional[Set[str]] = None,
) -> str:
    return _build_user_text_from_dynamic_bindings(
        input_payload=input_payload,
        dynamic_bindings=dynamic_bindings,
        consumed_binding_ids=consumed_binding_ids,
    )