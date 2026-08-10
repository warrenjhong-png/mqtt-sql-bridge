import json
import logging
import os
import threading
from datetime import datetime, timedelta


class RawJsonWriter:
    """將 MQTT 原始 payload 以每日一檔的 JSON Lines 格式保存。"""

    def __init__(self, raw_json_dir: str, logger: logging.Logger):
        self.raw_json_dir = raw_json_dir
        self.logger = logger
        self._lock = threading.Lock()
        self._current_date: str | None = None
        self._file = None
        os.makedirs(raw_json_dir, exist_ok=True)

    def write(self, table: str, payload: dict):
        # 鎖可避免寫入與跨日換檔同時發生。
        with self._lock:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != self._current_date:
                self._rotate(today)
            try:
                line = json.dumps(
                    {
                        "table": table,
                        "received_at": datetime.now().astimezone().isoformat(),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                )
                self._file.write(line + "\n")
                self._file.flush()
            except Exception as e:
                self.logger.error(f"RawJsonWriter write error: {e}")

    def _rotate(self, date_str: str):
        # append 模式可確保服務重啟後不覆蓋當日既有資料。
        if self._file:
            self._file.close()
        path = os.path.join(self.raw_json_dir, f"{date_str}.jsonl")
        self._file = open(path, "a", encoding="utf-8")
        self._current_date = date_str
        self.logger.info(f"RawJsonWriter rotated to {path}")
        self._cleanup_old_files()

    def _cleanup_old_files(self, keep_days: int = 7):
        # 僅清除檔名符合 YYYY-MM-DD.jsonl 且超過保留期的檔案。
        cutoff = datetime.now() - timedelta(days=keep_days)
        for filename in os.listdir(self.raw_json_dir):
            if not filename.endswith(".jsonl"):
                continue
            try:
                file_date = datetime.strptime(filename.replace(".jsonl", ""), "%Y-%m-%d")
                if file_date < cutoff:
                    os.remove(os.path.join(self.raw_json_dir, filename))
                    self.logger.info(f"RawJsonWriter deleted old file: {filename}")
            except ValueError:
                pass

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None
