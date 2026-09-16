# ragstream/textforge/FileSink.py
# -*- coding: utf-8 -*-
"""
FileSink
========

Concrete sink for durable file output.

Responsibilities:
- Accept/reject by severity type and sensitivity.
- Format final text through TextSink.
- Write full log text to file.
- Optionally write SQLite metadata after successful file write.
- Optionally run file/SQLite writing through one internal worker thread.

Important:
- Full log text goes to the log file.
- SQLite stores metadata/index only, not the full log text.
"""

from __future__ import annotations

import atexit
import logging
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Optional

from ragstream.textforge.TextSink import TextSink


class FileSink(TextSink):
    """
    Concrete file sink.

    If b_async is False:
        log() writes immediately.

    If b_async is True:
        log() puts the job into an internal queue.
        One worker thread writes file first, then SQLite metadata if enabled.
    """

    def __init__(
        self,
        path: str,
        accept_types: list[str],
        accept_sensitivities: list[str],
        rotation_size: int,
        split_flag: bool,
        b_sqlite: bool = False,
        sqlite_path: Optional[str] = None,
        b_async: bool = False,
        b_timestamp: bool = True,
        b_prefix: bool = True,
        b_suffix: bool = False,
    ) -> None:
        """
        Initialize file sink and file-specific options.

        Args:
            path:
                Exact target log file path.
            accept_types:
                Severity types this sink accepts.
            accept_sensitivities:
                Sensitivity flags this sink accepts.
            rotation_size:
                Max file size before rotation is used, if split_flag=True.
            split_flag:
                If True, RotatingFileHandler is used.
            b_sqlite:
                If True, write metadata to SQLite after file write.
            sqlite_path:
                SQLite database path; required when b_sqlite=True.
            b_async:
                If True, use one internal worker thread.
        """
        super().__init__(
            sink_kind="file",
            accept_types=accept_types,
            accept_sensitivities=accept_sensitivities,
            b_timestamp=b_timestamp,
            b_prefix=b_prefix,
            b_suffix=b_suffix,
        )

        self.path: str = path
        self.rotation_size: int = rotation_size
        self.split_flag: bool = split_flag
        self.b_sqlite: bool = b_sqlite
        self.sqlite_path: Optional[str] = sqlite_path
        self.b_async: bool = b_async

        self._closed: bool = False
        self._queue: Optional[Queue[tuple[str, str, str, str, str]]] = None
        self._worker_thread: Optional[threading.Thread] = None

        self._log_path = Path(self.path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        if self.b_sqlite:
            if not self.sqlite_path:
                raise ValueError("sqlite_path is required when b_sqlite=True.")
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self._ensure_sqlite_schema()

        self._logger = self._create_python_logger()

        if self.b_async:
            self._start_worker()
            atexit.register(self.close)

    def log(
        self,
        id: str,
        text: str,
        type: str,
        sensitivity: str,
    ) -> None:
        """
        Write one accepted log entry to file and optionally SQLite metadata.

        Order:
            1. Check type/sensitivity.
            2. Format final text.
            3. If async: queue job.
            4. If sync: write file first, then SQLite metadata.
        """
        if self._closed:
            return

        if not self.accepts(type=type, sensitivity=sensitivity):
            return

        final_text = self._format_text(
            id=id,
            text=text,
            type=type,
            sensitivity=sensitivity,
        )

        if self.b_async:
            assert self._queue is not None
            self._queue.put((id, final_text, type, sensitivity, text))
            return

        self._write_entry_sync(
            id=id,
            final_text=final_text,
            type=type,
            sensitivity=sensitivity,
            raw_text=text,
        )

    def close(self) -> None:
        """
        Flush/close async resources if they exist.

        For synchronous FileSink, this only marks the sink as closed.
        """
        if self._closed:
            return

        if self.b_async and self._queue is not None:
            self._queue.put(("", "", "", "", ""))  # sentinel
            self._queue.join()

            if self._worker_thread is not None:
                self._worker_thread.join(timeout=5.0)

        for handler in list(self._logger.handlers):
            handler.flush()
            handler.close()
            self._logger.removeHandler(handler)

        self._closed = True

    def _create_python_logger(self) -> logging.Logger:
        """
        Create an isolated Python logger for this FileSink.

        This is an implementation detail. Application code never sees it.
        """
        logger = logging.getLogger(f"TextForge.FileSink.{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        if self.split_flag and self.rotation_size > 0:
            handler: logging.Handler = RotatingFileHandler(
                filename=str(self._log_path),
                maxBytes=self.rotation_size,
                backupCount=100,
                encoding="utf-8",
            )
        else:
            handler = logging.FileHandler(
                filename=str(self._log_path),
                encoding="utf-8",
            )

        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        return logger

    def _start_worker(self) -> None:
        """
        Start one internal worker thread for asynchronous writing.
        """
        self._queue = Queue()

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"TextForgeFileSinkWorker-{id(self)}",
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        """
        Worker loop for async mode.

        Each queued item is written in the same order:
            file first, then SQLite metadata.
        """
        assert self._queue is not None

        while True:
            item = self._queue.get()

            try:
                log_id, final_text, type, sensitivity, raw_text = item

                # Sentinel means stop.
                if not log_id:
                    return

                self._write_entry_sync(
                    id=log_id,
                    final_text=final_text,
                    type=type,
                    sensitivity=sensitivity,
                    raw_text=raw_text,
                )

            except Exception as exc:
                # Logging failures should not silently disappear.
                # We avoid recursive logging here and write directly to stderr.
                print(
                    f"[TextForge FileSink worker error] {exc}",
                    file=sys.stderr,
                    flush=True,
                )

            finally:
                self._queue.task_done()

    def _write_entry_sync(
        self,
        id: str,
        final_text: str,
        type: str,
        sensitivity: str,
        raw_text: str,
    ) -> None:
        """
        Synchronous implementation used by both sync and async paths.

        This is the real FileSink write sequence:
            1. write full log text to file
            2. write SQLite metadata if enabled
        """
        self._logger.info(final_text)

        # Force handlers to flush so the file write is pushed out of Python buffers.
        for handler in self._logger.handlers:
            handler.flush()

        if self.b_sqlite:
            self._write_sqlite_metadata(
                id=id,
                type=type,
                sensitivity=sensitivity,
                raw_text=raw_text,
            )

    def _ensure_sqlite_schema(self) -> None:
        """
        Create SQLite metadata table if it does not exist.

        SQLite stores index/metadata only, not full log text.
        """
        assert self.sqlite_path is not None

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS textforge_log_index (
                    id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    type TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    text_length INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def _write_sqlite_metadata(
        self,
        id: str,
        type: str,
        sensitivity: str,
        raw_text: str,
    ) -> None:
        """
        Write SQLite metadata after file write.

        Stored:
            id
            UTC timestamp
            severity type
            sensitivity
            file path
            raw text length

        Not stored:
            full log text
        """
        assert self.sqlite_path is not None

        created_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with sqlite3.connect(self.sqlite_path, timeout=30.0) as conn:
            conn.execute(
                """
                INSERT INTO textforge_log_index (
                    id,
                    created_at_utc,
                    type,
                    sensitivity,
                    file_path,
                    text_length
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    created_at_utc,
                    type,
                    sensitivity,
                    str(self._log_path),
                    len(raw_text),
                ),
            )
            conn.commit()