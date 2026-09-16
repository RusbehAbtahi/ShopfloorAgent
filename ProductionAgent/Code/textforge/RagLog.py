# ragstream/textforge/RagLog.py
# -*- coding: utf-8 -*-
"""
RagLog
======

Project-level TextForge preset/builder layer.

Responsibilities:
- Create the fixed 4-sink RAGstream logging setup.
- Keep the 5 core classes neutral.
- Decide sink order, sink flags, paths, accepted severities, and accepted sensitivities.
- Provide ready-made logger entry points:
    LogALL()
    LogNoGUI()
    LogConf()
    LOGDeveloper()

Fixed sink order:
    sinks[0] = Sink0_Archive
    sinks[1] = File_PublicRun
    sinks[2] = CliRuntimeSink
    sinks[3] = GuiPublicSink

Developer logger:
    LOGDeveloper()
    - Standalone TextForge.
    - One single FileSink only.
    - Writes to data/logs/developer/.
    - Accepts all types and all sensitivities.
    - Async file writing enabled.
    - Controlled globally by B_developer.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from ragstream.textforge.TextForge import TextForge
from ragstream.textforge.TextSink import TextSink
from ragstream.textforge.FileSink import FileSink
from ragstream.textforge.CliSink import CliSink
from ragstream.textforge.GUISink import GuiSink


# ---------------------------------------------------------------------
# Global developer logging switch
# ---------------------------------------------------------------------

B_developer: bool = True


# ---------------------------------------------------------------------
# Fixed catalogs / presets used by RagLog
# ---------------------------------------------------------------------

ALL_TYPES: list[str] = [
    "TRACE",
    "DEBUG",
    "INFO",
    "WARN",
    "ERROR",
    "FATAL",
]

RUNTIME_TYPES: list[str] = [
    "INFO",
    "WARN",
    "ERROR",
    "FATAL",
]

ARCHIVE_SENSITIVITIES: list[str] = [
    "PUBLIC",
    "INTERNAL",
    "CONFIDENTIAL",
]

PUBLIC_ONLY: list[str] = [
    "PUBLIC",
]

CLI_NORMAL_SENSITIVITIES: list[str] = [
    "PUBLIC",
    "INTERNAL",
]

CLI_DEVELOPER_SENSITIVITIES: list[str] = [
    "PUBLIC",
    "INTERNAL",
    "CONFIDENTIAL",
]

DEVELOPER_ALL_SENSITIVITIES: list[str] = [
    "PUBLIC",
    "INTERNAL",
    "CONFIDENTIAL",
    "HIGHLY_CONFIDENTIAL",
]


_LOG_ALL: TextForge | None = None
_LOG_NO_GUI: TextForge | None = None
_LOG_CONF: TextForge | None = None
_LOG_DEVELOPER: TextForge | None = None


# ---------------------------------------------------------------------
# 1) CreateSinks
# ---------------------------------------------------------------------

def CreateSinks(
    mode: str = "normal",
    session_state: Optional[object] = None,
    gui_key: str = "textforge_gui_log",
    log_root: Optional[str | Path] = None,
    public_run_rotation_size: int = 10_000_000,
    archive_rotation_size: int = 50_000_000,
) -> list[TextSink]:
    """
    Create the fixed 4 sinks in the agreed order.

    Sink order:
        sinks[0] = Sink0_Archive
        sinks[1] = File_PublicRun
        sinks[2] = CliRuntimeSink
        sinks[3] = GuiPublicSink
    """

    if mode not in {"normal", "developer"}:
        raise ValueError("mode must be 'normal' or 'developer'.")

    project_root = Path(__file__).resolve().parents[2]

    if log_root is None:
        logs_root = project_root / "data" / "logs"
    else:
        logs_root = Path(log_root)

    today = date.today().isoformat()

    public_run_dir = logs_root / "public_run"
    archive_dir = logs_root / "archive"
    sqlite_dir = logs_root / "sqlite"

    public_run_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    sqlite_dir.mkdir(parents=True, exist_ok=True)

    public_run_path = public_run_dir / f"public_run_{today}.log"
    archive_path = archive_dir / f"archive_{today}.log"
    sqlite_path = sqlite_dir / "textforge_index.sqlite3"

    if session_state is None:
        try:
            import streamlit as st  # type: ignore
            session_state = st.session_state
        except Exception:
            session_state = {}

    sink0_archive = FileSink(
        path=str(archive_path),
        accept_types=ALL_TYPES,
        accept_sensitivities=ARCHIVE_SENSITIVITIES,
        rotation_size=archive_rotation_size,
        split_flag=True,
        b_sqlite=True,
        sqlite_path=str(sqlite_path),
        b_async=True,
        b_timestamp=True,
        b_prefix=True,
        b_suffix=False,
    )

    sink1_public_run = FileSink(
        path=str(public_run_path),
        accept_types=RUNTIME_TYPES,
        accept_sensitivities=PUBLIC_ONLY,
        rotation_size=public_run_rotation_size,
        split_flag=True,
        b_sqlite=False,
        sqlite_path=None,
        b_async=False,
        b_timestamp=True,
        b_prefix=True,
        b_suffix=False,
    )

    if mode == "developer":
        cli_types = ALL_TYPES
        cli_sensitivities = CLI_DEVELOPER_SENSITIVITIES
    else:
        cli_types = RUNTIME_TYPES
        cli_sensitivities = CLI_NORMAL_SENSITIVITIES

    sink2_cli = CliSink(
        stream="stdout",
        accept_types=cli_types,
        accept_sensitivities=cli_sensitivities,
        b_timestamp=True,
        b_prefix=True,
        b_suffix=False,
    )

    sink3_gui = GuiSink(
        session_state=session_state,
        key=gui_key,
        accept_types=RUNTIME_TYPES,
        accept_sensitivities=PUBLIC_ONLY,
        display_mode="prepend",
        b_timestamp=True,
        b_prefix=True,
        b_suffix=False,
    )

    return [
        sink0_archive,
        sink1_public_run,
        sink2_cli,
        sink3_gui,
    ]


# ---------------------------------------------------------------------
# 2) CreateTextForge
# ---------------------------------------------------------------------

def CreateTextForge(
    text: str = "",
    type: str = "INFO",
    sensitivity: str = "PUBLIC",
    mode: str = "normal",
    session_state: Optional[object] = None,
    gui_key: str = "textforge_gui_log",
    log_root: Optional[str | Path] = None,
    b_enable: Optional[list[bool]] = None,
) -> TextForge:
    """
    Create one TextForge logger with all 4 sinks attached.
    """

    sinks = CreateSinks(
        mode=mode,
        session_state=session_state,
        gui_key=gui_key,
        log_root=log_root,
    )

    if b_enable is None:
        b_enable = [True, True, True, True]

    return TextForge(
        text=text,
        type=type,
        sensitivity=sensitivity,
        sinks=sinks,
        b_enable=b_enable,
    )


# ---------------------------------------------------------------------
# 3) CreateDeveloperTextForge
# ---------------------------------------------------------------------

def CreateDeveloperTextForge(
    text: str = "",
    type: str = "DEBUG",
    sensitivity: str = "CONFIDENTIAL",
    log_root: Optional[str | Path] = None,
    developer_rotation_size: int = 100_000_000,
) -> TextForge:
    """
    Create the standalone developer TextForge.

    This logger is intentionally separate from the normal 4-sink runtime logger.

    Sink model:
        sinks[0] = Developer_FileSink

    Routing:
        b_enable = [B_developer]

    Behavior:
        If B_developer is True:
            Developer messages are written to data/logs/developer/.
        If B_developer is False:
            The logger call remains valid, but no sink receives the message.

    Intended use:
        Detailed development diagnostics:
        - token reports
        - variable dumps
        - stage internals
        - prompt fragments
        - model/debug metadata
    """

    project_root = Path(__file__).resolve().parents[2]

    if log_root is None:
        logs_root = project_root / "data" / "logs"
    else:
        logs_root = Path(log_root)

    today = date.today().isoformat()

    developer_dir = logs_root / "developer"
    developer_dir.mkdir(parents=True, exist_ok=True)

    developer_path = developer_dir / f"developer_{today}.log"

    developer_sink = FileSink(
        path=str(developer_path),
        accept_types=ALL_TYPES,
        accept_sensitivities=DEVELOPER_ALL_SENSITIVITIES,
        rotation_size=developer_rotation_size,
        split_flag=True,
        b_sqlite=False,
        sqlite_path=None,
        b_async=True,
        b_timestamp=True,
        b_prefix=True,
        b_suffix=False,
    )

    return TextForge(
        text=text,
        type=type,
        sensitivity=sensitivity,
        sinks=[developer_sink],
        b_enable=[bool(B_developer)],
    )


# ---------------------------------------------------------------------
# 4) LogALL
# ---------------------------------------------------------------------

def LogALL(
    text: str = "",
    type: str = "INFO",
    sensitivity: str = "PUBLIC",
    mode: str = "normal",
    session_state: Optional[object] = None,
    gui_key: str = "textforge_gui_log",
    log_root: Optional[str | Path] = None,
) -> TextForge:
    """
    Log through all 4 sinks.

    Routing:
        b_enable = [1, 1, 1, 1]

    Filtering:
        Only the sinks decide by accept_types and accept_sensitivities.
    """

    global _LOG_ALL

    if _LOG_ALL is None or session_state is not None or log_root is not None:
        _LOG_ALL = CreateTextForge(
            mode=mode,
            session_state=session_state,
            gui_key=gui_key,
            log_root=log_root,
            b_enable=[True, True, True, True],
        )

    if text:
        _LOG_ALL(text, type, sensitivity)

    return _LOG_ALL


# ---------------------------------------------------------------------
# 5) LogNoGUI
# ---------------------------------------------------------------------

def LogNoGUI(
    text: str = "",
    type: str = "INFO",
    sensitivity: str = "PUBLIC",
    mode: str = "normal",
    session_state: Optional[object] = None,
    gui_key: str = "textforge_gui_log",
    log_root: Optional[str | Path] = None,
) -> TextForge:
    """
    Log through all sinks except GUI.

    Routing:
        b_enable = [1, 1, 1, 0]

    Filtering:
        Only the sinks decide by accept_types and accept_sensitivities.
    """

    global _LOG_NO_GUI

    if _LOG_NO_GUI is None or session_state is not None or log_root is not None:
        _LOG_NO_GUI = CreateTextForge(
            mode=mode,
            session_state=session_state,
            gui_key=gui_key,
            log_root=log_root,
            b_enable=[True, True, True, False],
        )

    if text:
        _LOG_NO_GUI(text, type, sensitivity)

    return _LOG_NO_GUI


# ---------------------------------------------------------------------
# 6) LogConf
# ---------------------------------------------------------------------

def LogConf(
    text: str = "",
    type: str = "INFO",
    sensitivity: str = "PUBLIC",
    mode: str = "normal",
    session_state: Optional[object] = None,
    gui_key: str = "textforge_gui_log",
    log_root: Optional[str | Path] = None,
) -> TextForge:
    """
    Log only through archive.

    Routing:
        b_enable = [1, 0, 0, 0]

    Filtering:
        Only the archive sink decides by accept_types and accept_sensitivities.
    """

    global _LOG_CONF

    if _LOG_CONF is None or session_state is not None or log_root is not None:
        _LOG_CONF = CreateTextForge(
            mode=mode,
            session_state=session_state,
            gui_key=gui_key,
            log_root=log_root,
            b_enable=[True, False, False, False],
        )

    if text:
        _LOG_CONF(text, type, sensitivity)

    return _LOG_CONF


# ---------------------------------------------------------------------
# 7) LOGDeveloper
# ---------------------------------------------------------------------

def LOGDeveloper(
    text: str = "",
    type: str = "DEBUG",
    sensitivity: str = "CONFIDENTIAL",
    log_root: Optional[str | Path] = None,
) -> TextForge:
    """
    Standalone developer logger.

    Import pattern:
        from ragstream.textforge.RagLog import LogDeveloper as _logger_dev

    Usage:
        logger_dev("A4 token usage: ...", "DEBUG", "CONFIDENTIAL")
        logger_dev(f"sp.extras = {sp.extras}", "TRACE", "CONFIDENTIAL")

    Routing:
        b_enable = [B_developer]

    If B_developer is False:
        Existing logger_dev(...) lines remain in the code,
        but no developer message is written.
    """

    global _LOG_DEVELOPER

    if _LOG_DEVELOPER is None or log_root is not None:
        _LOG_DEVELOPER = CreateDeveloperTextForge(
            log_root=log_root,
        )

    _LOG_DEVELOPER.b_enable = [bool(B_developer)]

    if text:
        _LOG_DEVELOPER(text, type, sensitivity)

    return _LOG_DEVELOPER


# ---------------------------------------------------------------------
# 8) LogDeveloper compatibility alias
# ---------------------------------------------------------------------

def LogDeveloper(
    text: str = "",
    type: str = "DEBUG",
    sensitivity: str = "CONFIDENTIAL",
    log_root: Optional[str | Path] = None,
) -> TextForge:
    """
    Compatibility alias for LOGDeveloper.

    Preferred name:
        LOGDeveloper
    """

    return LOGDeveloper(
        text=text,
        type=type,
        sensitivity=sensitivity,
        log_root=log_root,
    )