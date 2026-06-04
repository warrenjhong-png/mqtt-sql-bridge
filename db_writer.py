import logging
import queue
import threading
from typing import Dict

import pyodbc


class DBWriter:
    def __init__(
        self,
        db_config,
        field_mapping: Dict[str, str],
        msg_queue: queue.Queue,
        logger: logging.Logger,
    ):
        self.db_config = db_config
        self.msg_queue = msg_queue
        self.logger = logger

        # Sort by FIELD_x key to guarantee consistent column order
        self._fields = sorted(field_mapping.items())

        self._conn = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="DBWriter", daemon=True)

    def start(self):
        self._thread.start()
        self.logger.info("DBWriter started")

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=15)
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self.logger.info("DBWriter stopped")

    def _connect(self):
        conn_str = (
            f"DRIVER={{{self.db_config.driver}}};"
            f"SERVER={self.db_config.server};"
            f"DATABASE={self.db_config.database};"
            f"UID={self.db_config.username};"
            f"PWD={self.db_config.password};"
            "TrustServerCertificate=yes;"
        )
        self._conn = pyodbc.connect(conn_str, timeout=10)
        self.logger.info(f"DB connected to {self.db_config.server}/{self.db_config.database}")

    def _reconnect(self) -> bool:
        try:
            self._connect()
            return True
        except Exception as e:
            self.logger.warning(
                f"DB reconnect failed: {e}, retry in {self.db_config.reconnect_delay}s"
            )
            self._stop_event.wait(self.db_config.reconnect_delay)
            return False

    def _insert(self, table: str, payload: dict):
        field_names = [f for f, _ in self._fields]
        values = [payload.get(key) for _, key in self._fields]

        columns = ", ".join(field_names)
        placeholders = ", ".join(["?"] * len(field_names))
        sql = f"INSERT INTO [{table}] (TIMETAG, {columns}) VALUES (GETDATE(), {placeholders})"

        cursor = self._conn.cursor()
        cursor.execute(sql, values)
        self._conn.commit()

    def _run(self):
        while not self._stop_event.is_set():
            if self._conn is None:
                if not self._reconnect():
                    continue

            try:
                item = self.msg_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                self._insert(item["table"], item["payload"])
            except pyodbc.Error as e:
                self.logger.error(f"DB insert error: {e} (data saved in raw_json)")
                self._conn = None
            except Exception as e:
                self.logger.error(f"Unexpected DB error: {e}")
            finally:
                self.msg_queue.task_done()
