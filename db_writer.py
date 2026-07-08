import logging
import queue
import threading
import time
from datetime import datetime
from typing import Dict

import pyodbc

KEEPALIVE_INTERVAL = 300  # seconds, ping DB every 5 minutes to prevent idle disconnect


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
        self._last_keepalive = 0.0
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

        timetag = None
        timetag_str = payload.get("Timestamp")
        if timetag_str:
            try:
                timetag = datetime.fromisoformat(timetag_str)
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid Timestamp format: {timetag_str!r}, falling back to GETDATE()")

        columns = ", ".join(field_names)
        placeholders = ", ".join(["?"] * len(field_names))
        if timetag is not None:
            sql = f"INSERT INTO [{table}] (TIMETAG, TIME01, {columns}) VALUES (?, GETDATE(), {placeholders})"
            values = [timetag] + values
        else:
            sql = f"INSERT INTO [{table}] (TIMETAG, TIME01, {columns}) VALUES (GETDATE(), GETDATE(), {placeholders})"

        cursor = self._conn.cursor()
        cursor.execute(sql, values)
        self._conn.commit()

    def _keepalive(self):
        """Send a lightweight query to prevent idle connection drop by firewall/server."""
        try:
            self._conn.cursor().execute("SELECT 1")
            self._last_keepalive = time.monotonic()
        except Exception as e:
            self.logger.warning(f"DB keepalive failed: {e}, will reconnect")
            self._conn = None

    def _run(self):
        while not self._stop_event.is_set():
            if self._conn is None:
                if not self._reconnect():
                    continue

            try:
                item = self.msg_queue.get(timeout=1)
            except queue.Empty:
                # No messages — check if keepalive is due
                if time.monotonic() - self._last_keepalive >= KEEPALIVE_INTERVAL:
                    self._keepalive()
                continue

            try:
                self._insert(item["table"], item["payload"])
                self._last_keepalive = time.monotonic()  # insert counts as activity
            except pyodbc.Error as e:
                sqlstate = e.args[0] if e.args else ""
                if sqlstate == "23000":
                    # Duplicate primary key — another instance already wrote this record, skip silently
                    self.logger.debug(f"Duplicate record skipped (another instance may have written it): {e}")
                else:
                    # Real connection error — trigger reconnect
                    self.logger.error(f"DB insert error: {e} (data saved in raw_json)")
                    self._conn = None
            except Exception as e:
                self.logger.error(f"Unexpected DB error: {e}")
            finally:
                self.msg_queue.task_done()
