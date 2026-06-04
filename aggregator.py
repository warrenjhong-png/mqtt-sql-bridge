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

    def ingest(self, table: str, payload: dict):
        """Called by MQTTReceiver on every incoming message."""
        if self.interval == 0:
            # Pass-through: directly enqueue
            self._enqueue(table, payload)
        else:
            with self._lock:
                self._buffers.setdefault(table, []).append(payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        while not self._stop_event.wait(timeout=self.interval):
            self._flush(reason="interval")

    def _flush(self, reason: str = "interval"):
        with self._lock:
            buffers_snapshot = self._buffers
            self._buffers = {}

        for table, payloads in buffers_snapshot.items():
            if not payloads:
                continue
            averaged = self._average(payloads)
            self.logger.debug(
                f"[{reason}] Aggregated {len(payloads)} sample(s) → {table}"
            )
            self._enqueue(table, averaged)

    def _enqueue(self, table: str, payload: dict):
        try:
            self.msg_queue.put_nowait({"table": table, "payload": payload})
        except queue.Full:
            self.logger.warning("Queue is full, dropping message")

    @staticmethod
    def _average(payloads: List[dict]) -> dict:
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
