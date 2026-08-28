from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Sequence


class RulesProtocolError(RuntimeError):
    pass


class NativeRulesClient:
    """Request-ID JSONL client for the C++ rules authority."""

    def __init__(self, command: str | Path | Sequence[str | Path], timeout: float = 10.0):
        argv = [str(command)] if isinstance(command, (str, Path)) else [str(x) for x in command]
        if not argv or timeout <= 0:
            raise ValueError("rules command and timeout must be valid")
        self.timeout = timeout
        self._next_id = 1
        self._lock = threading.Lock()
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._read_output, daemon=True).start()
        self.new_game()

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _request(self, method: str, **params: Any) -> dict[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise RulesProtocolError(f"rules process exited with code {self._process.returncode}")
            request_id = str(self._next_id)
            self._next_id += 1
            payload = {"id": request_id, "method": method, **params}
            assert self._process.stdin is not None
            self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for rules method {method}")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty as error:
                    raise TimeoutError(f"timed out waiting for rules method {method}") from error
                if line is None:
                    raise RulesProtocolError("rules process exited during a request")
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if response.get("id") != request_id:
                    raise RulesProtocolError("rules response request ID is out of sequence")
                if not response.get("ok"):
                    raise RulesProtocolError(str(response.get("error", "unknown rules error")))
                data = response.get("data")
                if not isinstance(data, dict):
                    raise RulesProtocolError("rules response data must be an object")
                return data

    def new_game(self) -> dict[str, Any]:
        return self._request("newGame")

    def snapshot(self) -> dict[str, Any]:
        return self._request("snapshot")

    def play_move(self, move: str) -> dict[str, Any]:
        if "\n" in move or "\r" in move:
            raise ValueError("move must be a single line")
        return self._request("playMove", move=move)

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                self._request("quit")
                self._process.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired, RulesProtocolError):
                self._process.kill()
                self._process.wait(timeout=2)
        if self._process.stdin is not None:
            self._process.stdin.close()
        if self._process.stdout is not None:
            self._process.stdout.close()

    def __enter__(self) -> NativeRulesClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
