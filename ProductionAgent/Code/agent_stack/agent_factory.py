# -*- coding: utf-8 -*-
"""
AgentFactory
============

- This is the single place where AgentPrompt objects are created from JSON configs.
- It hides all file-system details (where JSON lives, how paths are built).
- It also caches created agents, so JSON is read only once per (agent_id, version).

Usage model (high level):
- Controller creates ONE AgentFactory instance at startup.
- Each Agent (A2, A3, ...) asks this factory for its AgentPrompt:
    factory.get_agent("a2_promptshaper", "003")
- The returned AgentPrompt is then used to compose/parse LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app_logging.agent_logger import SimpleLogger
from .agent_prompt import AgentPrompt


class AgentFactory:
    """
    Central factory for building and caching AgentPrompt instances.

    Design goals:
    - Neutral: knows nothing about A2/A3/etc. beyond their (agent_id, version).
    - File-based: loads JSON configs from data/agents/<agent_id>/<version>.json.
    - Cached: Agents are constructed once and reused for the lifetime of the factory.
    """

    def __init__(self, agents_root: Optional[Path] = None) -> None:
        if agents_root is None:
            repo_root = Path(__file__).resolve().parents[2]
            agents_root = repo_root / "data" / "agents"

        self.agents_root: Path = agents_root
        self._cache: Dict[Tuple[str, str], AgentPrompt] = {}

        SimpleLogger.info(f"AgentFactory initialized with agents_root={self.agents_root}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_config_path(self, agent_id: str, version: str) -> Path:
        return self.agents_root / agent_id / f"{version}.json"

    def _load_json_file(self, path: Path) -> Dict[str, Any]:
        if not path.is_file():
            msg = f"AgentFactory: JSON file not found at {path}"
            SimpleLogger.error(msg)
            raise FileNotFoundError(msg)

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            msg = f"AgentFactory: failed to load JSON from {path}: {exc}"
            SimpleLogger.error(msg)
            raise RuntimeError(msg) from exc

        if not isinstance(data, dict):
            msg = f"AgentFactory: top-level JSON in {path} must be an object/dict"
            SimpleLogger.error(msg)
            raise ValueError(msg)

        return data

    def _extract_catalog_block(
        self,
        *,
        catalog: Dict[str, Any],
        target_id: str,
        catalog_path: Path,
    ) -> Dict[str, Any]:
        """
        Extract one decision-target block from an external catalog.

        Supported neutral shapes:

        1) Wrapped-by-target_id
           {
             "system": {
               "options": [...],
               "default": ...
             }
           }

        2) Direct/root block
           {
             "options": [...],
             "default": ...
           }

        3) Single-valid-block fallback
           {
             "<some_other_name>": {
               "options": [...],
               "default": ...
             }
           }

        Shape (3) remains neutral and is accepted only when there is exactly
        one valid block in the catalog, so no agent-specific logic is needed.
        """
        exact_block = catalog.get(target_id)
        if isinstance(exact_block, dict):
            return exact_block

        root_options = catalog.get("options")
        if isinstance(root_options, list):
            return catalog

        valid_blocks: Dict[str, Dict[str, Any]] = {}
        for key, value in catalog.items():
            if isinstance(value, dict) and isinstance(value.get("options"), list):
                valid_blocks[key] = value

        if len(valid_blocks) == 1:
            block_name, block = next(iter(valid_blocks.items()))
            SimpleLogger.info(
                "AgentFactory: catalog fallback accepted single valid block "
                f"'{block_name}' for decision_target id='{target_id}' from {catalog_path}"
            )
            return block

        msg = (
            f"AgentFactory: catalog {catalog_path} does not contain a valid block "
            f"for decision_target id='{target_id}'"
        )
        SimpleLogger.error(msg)
        raise KeyError(msg)

    def _resolve_decision_targets(
        self,
        *,
        config: Dict[str, Any],
        cfg_path: Path,
    ) -> Dict[str, Any]:
        """
        Resolve external catalog references inside decision_targets.

        Neutral convention:
        - main config contains decision_targets
        - each target may point to an external catalog file via:
              "options": "a2_catalogs/003_option_catalogs_system.json"
        - supported external catalog shapes are handled by _extract_catalog_block()

        Result:
        - options path string is replaced by the real inline options list
        - default from the catalog is copied into the decision target
        """
        targets = config.get("decision_targets")
        if not isinstance(targets, list):
            return config

        resolved_targets = []
        base_dir = cfg_path.parent

        for target in targets:
            if not isinstance(target, dict):
                continue

            target_id = target.get("id")
            if not target_id:
                continue

            resolved = dict(target)
            options_ref = resolved.get("options")

            if isinstance(options_ref, str):
                catalog_path = base_dir / options_ref
                catalog = self._load_json_file(catalog_path)
                block = self._extract_catalog_block(
                    catalog=catalog,
                    target_id=str(target_id),
                    catalog_path=catalog_path,
                )

                options_list = block.get("options", [])
                if not isinstance(options_list, list):
                    msg = (
                        f"AgentFactory: catalog block for '{target_id}' in {catalog_path} "
                        f"has invalid 'options' (expected list)"
                    )
                    SimpleLogger.error(msg)
                    raise ValueError(msg)

                resolved["options"] = options_list

                if "default" in block:
                    resolved["default"] = block["default"]

            resolved_targets.append(resolved)

        config["decision_targets"] = resolved_targets
        return config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_config(self, agent_id: str, version: str) -> Dict[str, Any]:
        cfg_path = self._build_config_path(agent_id, version)
        config = self._load_json_file(cfg_path)
        config = self._resolve_decision_targets(config=config, cfg_path=cfg_path)
        return config

    def get_agent(self, agent_id: str, version: str = "001") -> AgentPrompt:
        key = (agent_id, version)
        if key in self._cache:
            return self._cache[key]

        config = self.load_config(agent_id, version)
        agent = AgentPrompt.from_config(config)
        self._cache[key] = agent

        SimpleLogger.info(
            f"AgentFactory: created AgentPrompt for agent_id={agent_id}, version={version}"
        )
        return agent

    def clear_cache(self) -> None:
        self._cache.clear()
        SimpleLogger.info("AgentFactory: cache cleared")