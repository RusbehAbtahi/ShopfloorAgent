# ragstream/textforge/CliSink.py
# -*- coding: utf-8 -*-
"""
CliSink
=======

Concrete sink for terminal / CLI output.

Responsibilities:
- Accept/reject by severity type and sensitivity.
- Format final text through TextSink.
- Write final text to stdout or stderr.

Important:
- Runtime/developer behavior is not hard-coded here.
- RagLog.py later decides which types/sensitivities this sink accepts.
"""

from __future__ import annotations

import sys
from typing import Literal

from ragstream.textforge.TextSink import TextSink


class CliSink(TextSink):
    """
    CLI sink.

    stream:
        "stdout"
        "stderr"
    """

    def __init__(
        self,
        stream: Literal["stdout", "stderr"],
        accept_types: list[str],
        accept_sensitivities: list[str],
        b_timestamp: bool = True,
        b_prefix: bool = True,
        b_suffix: bool = False,
    ) -> None:
        """
        Initialize CLI sink.

        Args:
            stream:
                Target stream name: "stdout" or "stderr".
            accept_types:
                Severity types this sink accepts.
            accept_sensitivities:
                Sensitivity flags this sink accepts.
        """
        super().__init__(
            sink_kind="cli",
            accept_types=accept_types,
            accept_sensitivities=accept_sensitivities,
            b_timestamp=b_timestamp,
            b_prefix=b_prefix,
            b_suffix=b_suffix,
        )

        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be 'stdout' or 'stderr'.")

        self.stream: Literal["stdout", "stderr"] = stream

    def log(
        self,
        id: str,
        text: str,
        type: str,
        sensitivity: str,
    ) -> None:
        """
        Write one accepted log entry to stdout or stderr.
        """
        if not self.accepts(type=type, sensitivity=sensitivity):
            return

        final_text = self._format_text(
            id=id,
            text=text,
            type=type,
            sensitivity=sensitivity,
        )

        target_stream = sys.stderr if self.stream == "stderr" else sys.stdout
        print(final_text, file=target_stream, flush=True)