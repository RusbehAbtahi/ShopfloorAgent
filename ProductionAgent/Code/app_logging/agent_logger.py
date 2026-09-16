"""Asynchronous normal and developer logging for ProductionAgent."""

from __future__ import annotations

import atexit
import json
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


PRODUCTION_AGENT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PRODUCTION_AGENT_ROOT / "data" / "log"
NORMAL_LOG_PATH = LOG_DIR / "normal.log"
DEVELOPER_LOG_PATH = LOG_DIR / "developer.log"
_REDACTED_KEYS = {
    "api_key",
    "openai_api_key",
    "authorization",
    "password",
    "secret",
    "client_secret",
}


@dataclass(frozen=True)
class _LogRecord:
    channel: str
    timestamp: str
    event: str
    payload: dict[str, Any]


class AgentLogger:
    """Queue application logs and write them on one background thread."""

    def __init__(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        NORMAL_LOG_PATH.touch(exist_ok=True)
        DEVELOPER_LOG_PATH.touch(exist_ok=True)
        # Added on 16.09.2026: remember existing file ends so GUI shows only logs from this app process.
        self._gui_start_offsets = {
            "normal": NORMAL_LOG_PATH.stat().st_size,
            "developer": DEVELOPER_LOG_PATH.stat().st_size,
        }
        self._queue: queue.Queue[_LogRecord | None] = queue.Queue()
        self._worker = threading.Thread(
            target=self._writer_loop,
            name="production-agent-log-writer",
            daemon=True,
        )
        self._worker.start()
        atexit.register(self.close)

    def normal(self, event: str, **fields: Any) -> None:
        """Queue one concise operational event."""
        self._enqueue("normal", event, fields)

    def developer(self, event: str, values: Mapping[str, Any] | None = None) -> None:
        """Queue a detailed diagnostic snapshot, normally with ``locals()``."""
        self._enqueue("developer", event, dict(values or {}))

    def read_tail(self, channel: str, max_lines: int = 80) -> str:
        """Return a bounded log tail for the Streamlit GUI sink."""
        self.flush()
        path = NORMAL_LOG_PATH if channel == "normal" else DEVELOPER_LOG_PATH
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                file_size = handle.tell()
                start_offset = min(int(self._gui_start_offsets.get(channel, 0)), file_size)
                handle.seek(start_offset)
                visible_text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        lines = visible_text.splitlines()
        return "\n".join(lines[-max(1, int(max_lines)) :])

    def flush(self, timeout: float = 2.0) -> None:
        """Wait briefly for pending records without blocking application flow."""
        deadline = time.monotonic() + max(0.0, timeout)
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def close(self) -> None:
        """Flush and stop the background writer once at interpreter shutdown."""
        if not self._worker.is_alive():
            return
        self.flush()
        self._queue.put(None)
        self._worker.join(timeout=1.0)

    def _enqueue(self, channel: str, event: str, payload: Mapping[str, Any]) -> None:
        self._queue.put(
            _LogRecord(
                channel=channel,
                timestamp=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                event=str(event),
                payload=self._sanitize_mapping(payload),
            )
        )

    def _writer_loop(self) -> None:
        while True:
            record = self._queue.get()
            try:
                if record is None:
                    return
                self._write(record)
            finally:
                self._queue.task_done()

    @staticmethod
    def _write(record: _LogRecord) -> None:
        path = NORMAL_LOG_PATH if record.channel == "normal" else DEVELOPER_LOG_PATH
        if record.channel == "normal":
            details = " | ".join(
                f"{key}={AgentLogger._compact(value)}"
                for key, value in record.payload.items()
            )
            text = f"[{record.timestamp}] {record.event}"
            if details:
                text += f" | {details}"
            # Added on 16.09.2026: one blank line keeps compact operational entries visually separable.
            text += "\n\n"
        else:
            body = json.dumps(record.payload, ensure_ascii=False, indent=2, default=str)
            text = f"[{record.timestamp}] {record.event}\n{body}\n\n"

        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    @classmethod
    def _sanitize_mapping(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        return {
            str(key): cls._sanitize_value(key=str(key), value=value)
            for key, value in values.items()
            if not str(key).startswith("__")
        }

    @classmethod
    def _sanitize_value(cls, *, key: str, value: Any) -> Any:
        if key.lower() in _REDACTED_KEYS:
            return "<redacted>"
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Mapping):
            return cls._sanitize_mapping(value)
        if isinstance(value, (list, tuple, set)):
            return [cls._sanitize_value(key=key, value=item) for item in value]
        if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
            return getattr(value, "value")
        return repr(value)

    @staticmethod
    def _compact(value: Any) -> str:
        if isinstance(value, str):
            return value.replace("\n", " ")[:220]
        return json.dumps(value, ensure_ascii=False, default=str)[:220]


LOGGER = AgentLogger()


class SimpleLogger:
    """Compatibility adapter for the copied neutral Agent Stack."""

    @staticmethod
    def info(message: Any) -> None:
        LOGGER.developer("agent_stack.info", {"message": str(message)})

    @staticmethod
    def warning(message: Any) -> None:
        LOGGER.developer("agent_stack.warning", {"message": str(message)})

    @staticmethod
    def error(message: Any) -> None:
        LOGGER.developer("agent_stack.error", {"message": str(message)})
