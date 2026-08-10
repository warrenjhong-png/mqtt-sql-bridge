import logging
import queue
import threading
from typing import Dict, List


class DataAggregator:
    """
    Downsampling aggregator.

    - interval_seconds == 0 : pass-through，每筆訊息直接進 queue。
    - interval_seconds  > 0 : 累積該時間窗口內的所有訊息，
                              計算數值欄位的平均值後才進 queue。
                              非數值欄位（如 timestamp）取最後一筆的值。
    """

    def __init__(
        self,
        interval_seconds: int,
        msg_queue: queue.Queue,
        logger: logging.Logger,
    ):
        self.interval = interval_seconds
        self.msg_queue = msg_queue
        self.logger = logger

        self._buffers: Dict[str, List[dict]] = {}  # table → list of payloads
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        if self.interval > 0:
            self._thread = threading.Thread(
                target=self._run, name="DataAggregator", daemon=True
            )
            self.logger.info(
                f"DataAggregator enabled: averaging window = {self.interval}s"
            )
        else:
            self._thread = None
            self.logger.info("DataAggregator disabled: pass-through mode")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if self._thread:
            self._thread.start()

    def stop(self):
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=10)
            # Flush remaining buffered data before shutdown
            self._flush(reason="shutdown")

    def ingest(self, table: str, payload: dict, context=None):
        """每收到一筆 MQTT 訊息即呼叫；依設定選擇直通或暫存。"""
        if self.interval == 0:
            self._enqueue(table, payload, context)
        else:
            with self._lock:
                self._buffers.setdefault(table, []).append((payload, context))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        while not self._stop_event.wait(timeout=self.interval):
            self._flush(reason="interval")

    def _flush(self, reason: str = "interval"):
        # 鎖內只交換 buffer；平均運算與 Queue 操作在鎖外執行。
        with self._lock:
            buffers_snapshot = self._buffers
            self._buffers = {}

        for table, entries in buffers_snapshot.items():
            if not entries:
                continue
            payloads = [p for p, _ in entries]
            context = entries[-1][1]
            averaged = self._average(payloads)
            self.logger.debug(
                f"[{reason}] Aggregated {len(payloads)} sample(s) → {table}"
            )
            self._enqueue(table, averaged, context)

    def _enqueue(self, table: str, payload: dict, context=None):
        try:
            # 不等待空位，以免 DB 過慢時反向阻塞 MQTT 收訊執行緒。
            self.msg_queue.put_nowait({"table": table, "payload": payload, "context": context})
        except queue.Full:
            self.logger.warning("Queue is full, dropping message")

    @staticmethod
    def _average(payloads: List[dict]) -> dict:
        """數值欄位取平均；文字與時間戳等非數值欄位取最後一筆。"""
        result = {}
        all_keys = payloads[0].keys()
        for key in all_keys:
            values = [p[key] for p in payloads if key in p and p[key] is not None]
            if values and isinstance(values[0], (int, float)):
                result[key] = sum(values) / len(values)
            else:
                # Non-numeric（如 timestamp）取最後一筆
                result[key] = payloads[-1].get(key)
        return result
