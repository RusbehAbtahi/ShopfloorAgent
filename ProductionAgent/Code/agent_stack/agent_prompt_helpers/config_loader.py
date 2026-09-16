# -*- coding: utf-8 -*-
"""
config_loader
=============

Why this helper exists:
- Agent JSON configs define decision targets with enums, defaults and selection counts.
- Converting these targets into clean Python dictionaries is generic logic and should
  not clutter AgentPrompt.

What it does:
- Provides a single function `extract_field_config(fields_cfg)` that returns:
  - enums[field_id] = list of allowed option ids
  - defaults[field_id] = default value from config (may be str or list)
  - cardinality[field_id] = "one" or "many"
  - option_labels[field_id][opt_id] = human-readable label (optional)
  - option_descriptions[field_id][opt_id] = human-readable description (optional)

Compatibility:
- Works with the new `decision_targets` structure.
- Also tolerates older inline `fields` configs, as long as they use the same
  basic keys (`id`, `type`, `options`, `default`, `cardinality`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def extract_field_config(
    fields_cfg: List[Dict[str, Any]]
) -> Tuple[
    Dict[str, List[str]],
    Dict[str, Any],
    Dict[str, str],
    Dict[str, Dict[str, str]],
    Dict[str, Dict[str, str]],
]:
    """
    Convert decision targets / fields into:
    - enums[field_id] = ["opt1", "opt2", ...]
    - defaults[field_id] = default value from config (may be str or list)
    - cardinality[field_id] = "one" | "many"
    - option_descriptions[field_id][opt_id] = description (if present)
    - option_labels[field_id][opt_id] = label (if present)
    """
    enums: Dict[str, List[str]] = {}
    defaults: Dict[str, Any] = {}
    cardinality: Dict[str, str] = {}
    option_descriptions: Dict[str, Dict[str, str]] = {}
    option_labels: Dict[str, Dict[str, str]] = {}

    for field in fields_cfg:
        field_id = field.get("id")
        if not field_id:
            continue

        field_type = field.get("type", "enum")
        if field_type != "enum":
            # For v1 implementation, AgentPrompt only supports enum-based Selector behaviour.
            continue

        options = field.get("options", []) or []
        if not isinstance(options, list):
            options = []

        allowed_ids: List[str] = []
        descs: Dict[str, str] = {}
        labels: Dict[str, str] = {}

        for opt in options:
            if not isinstance(opt, dict):
                continue

            opt_id = opt.get("id")
            if not opt_id:
                continue

            allowed_ids.append(opt_id)

            if "label" in opt:
                labels[opt_id] = opt["label"]
            if "description" in opt:
                descs[opt_id] = opt["description"]

        if allowed_ids:
            enums[field_id] = allowed_ids
            if labels:
                option_labels[field_id] = labels
            if descs:
                option_descriptions[field_id] = descs

        defaults[field_id] = field.get("default")

        if "cardinality" in field:
            cardinality[field_id] = field.get("cardinality", "one")
        else:
            try:
                max_selected = int(field.get("max_selected", 1))
            except Exception:
                max_selected = 1
            cardinality[field_id] = "many" if max_selected > 1 else "one"

    return enums, defaults, cardinality, option_descriptions, option_labels