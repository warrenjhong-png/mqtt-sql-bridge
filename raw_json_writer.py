import json
import logging
import os
import threading
from datetime import datetime


class RawJsonWriter:
    def __init__(self, raw_json_dir: str, logger: logging.Logger):
        self.raw_json_dir = raw_json_dir
        self.logger = logger
        self._lock = threading.Lock()
        self._current_date: str | None = None
        self._file = None
        os.makedirs(raw_json_dir, exist_ok=True)

    def write(self, table: str, payload: dict):
        with self._lock:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != self._current_date:
                self._rotate(today)
            try:
                line = json.dumps(
                    {"table": table, "payload": payload}, ensure_ascii=False
                )
                self._file.write(line + "\n")
                self._file.flush()
            except Exception as e:
                self.logger.error(f"RawJsonWriter write error: {e}")

    def _rotate(self, date_str: str):
        if self._file:
            self._file.close()
        path = os.path.join(self.raw_json_dir, f"{date_str}.jsonl")
        self._file = open(path, "a", encoding="utf-8")
        self._current_date = date_str
        self.logger.info(f"RawJsonWriter rotated to {path}")

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None
