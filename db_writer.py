import logging
import queue
import re
import threading
import time
from datetime import datetime
from typing import Dict

import pyodbc


KEEPALIVE_INTERVAL = 300
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DBWriter:
    """從 Queue 取出 MQTT 資料，寫入來源表並執行三表 dispatch。"""

    def __init__(
        self,
        db_config,
        dispatch_config,
        field_mapping: Dict[str, str],
        msg_queue: queue.Queue,
        logger: logging.Logger,
    ):
        self.db_config = db_config
        self.dispatch_config = dispatch_config
        self.msg_queue = msg_queue
        self.logger = logger

        # FIELD_x 與 JSON key 必須使用同一排序，才能保持欄位和值對應。
        self._fields = sorted(field_mapping.items())
        self._dispatch_tables = {
            source.table for source in self.dispatch_config.sources
        }
        self._validate_identifiers()

        self._conn = None
        self._last_keepalive = 0.0
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="DBWriter", daemon=True
        )

    def _validate_identifiers(self):
        """動態 SQL 的表名和欄名只能使用安全的 SQL 識別字。"""
        identifiers = [name for name, _ in self._fields]
        for source in self.dispatch_config.sources:
            identifiers.extend(
                [source.table, source.source_field, source.target_field]
            )
        invalid = [name for name in identifiers if not IDENTIFIER_PATTERN.fullmatch(name)]
        if invalid:
            raise ValueError(f"Invalid SQL identifier(s): {invalid}")

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
        self.logger.info(
            f"DB connected to {self.db_config.server}/{self.db_config.database}"
        )

    def _reconnect(self) -> bool:
        try:
            self._connect()
            return True
        except Exception as e:
            self.logger.warning(
                f"DB reconnect failed: {e}, retry in "
                f"{self.db_config.reconnect_delay}s"
            )
            self._stop_event.wait(self.db_config.reconnect_delay)
            return False

    def _payload_timestamp(self, payload: dict) -> datetime:
        """接受 Timestamp／timestamp，無效時才使用程式收到資料的時間。"""
        timestamp_text = payload.get("Timestamp") or payload.get("timestamp")
        if timestamp_text:
            try:
                return datetime.fromisoformat(timestamp_text)
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Invalid Timestamp format: {timestamp_text!r}, "
                    "falling back to current time"
                )
        return datetime.now()

    @staticmethod
    def _timestamp_serial(timetag: datetime) -> str:
        # 秒以下資訊刻意捨去：同一秒的七張來源表會得到相同 ID。
        return timetag.strftime("%Y%m%d%H%M%S")

    def _build_original_context_id(
        self, context, payload: dict, timetag: datetime
    ) -> str:
        """保留修改前 Parser 使用的完整 ID，寫入來源表 FIELD_20。"""
        module_type = payload.get("compressor_drive_type", "")
        serial = self._timestamp_serial(timetag)
        return (
            f"{context.factory_code}_{context.system_type}_"
            f"{context.equipment_type}_{context.machine_id}_"
            f"{module_type}_{serial}"
        )

    def _build_context_id(self, context, timetag: datetime) -> str:
        """建立七張來源表共用的新 ID：Factory_System_Timestamp。"""
        if self.dispatch_config.enabled:
            factory_code = self.dispatch_config.factory_code
            system_type = self.dispatch_config.system_type
        else:
            factory_code = context.factory_code
            system_type = context.system_type
        return (
            f"{factory_code}_{system_type}_{self._timestamp_serial(timetag)}"
        )

    def _insert(self, table: str, payload: dict, context=None):
        if not IDENTIFIER_PATTERN.fullmatch(table):
            raise ValueError(f"Invalid SQL table name: {table!r}")

        timetag = self._payload_timestamp(payload)
        context_id = self._build_context_id(context, timetag) if context else None
        original_context_id = (
            self._build_original_context_id(context, payload, timetag)
            if context
            else None
        )

        field_names = [field for field, _ in self._fields]
        values = [payload.get(key) for _, key in self._fields]

        # FIELD_20 專門保存修改前的 CONTEXTID，方便追溯舊資料命名。
        if "FIELD_20" not in field_names:
            field_names.append("FIELD_20")
            values.append(original_context_id)

        columns = ", ".join(field_names)
        placeholders = ", ".join(["?"] * len(field_names))
        sql = (
            f"INSERT INTO [{table}] "
            f"(CONTEXTID, TIMETAG, TIME01, {columns}) "
            f"VALUES (?, ?, GETDATE(), {placeholders})"
        )

        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, [context_id, timetag] + values)

            if self.dispatch_config.enabled and table in self._dispatch_tables:
                self._dispatch_if_ready(cursor, context_id, timetag)
            elif not self.dispatch_config.enabled and context:
                self._insert_legacy_related(
                    cursor, context_id, timetag, context, payload
                )

            # 來源表與可能產生的 METROLOGY／SYSSETTING 一次提交。
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _dispatch_if_ready(self, cursor, context_id: str, timetag: datetime):
        """三張指定來源表都有相同 CONTEXTID 時，才建立彙整資料。"""
        metrology_values = {}
        for source in self.dispatch_config.sources:
            sql = (
                f"SELECT TOP 1 [{source.source_field}] FROM [{source.table}] "
                "WHERE CONTEXTID = ?"
            )
            row = cursor.execute(sql, context_id).fetchone()
            if row is None:
                self.logger.debug(
                    f"Dispatch waiting: context_id={context_id}, "
                    f"missing_table={source.table}"
                )
                return
            metrology_values[source.target_field] = row[0]

        self._insert_metrology_if_missing(
            cursor, context_id, timetag, metrology_values
        )
        self._insert_syssetting_if_missing(cursor, context_id, timetag)
        self.logger.info(f"Dispatch completed: context_id={context_id}")

    @staticmethod
    def _record_exists(cursor, table: str, context_id: str) -> bool:
        row = cursor.execute(
            f"SELECT TOP 1 1 FROM [{table}] WHERE CONTEXTID = ?", context_id
        ).fetchone()
        return row is not None

    def _insert_metrology_if_missing(
        self, cursor, context_id: str, timetag: datetime, values_by_field: dict
    ):
        if self._record_exists(cursor, "METROLOGY", context_id):
            return

        columns = list(values_by_field.keys())
        placeholders = ", ".join(["?"] * len(columns))
        column_sql = ", ".join(f"[{column}]" for column in columns)
        sql = (
            "INSERT INTO [METROLOGY] "
            f"(CONTEXTID, TIMETAG, {column_sql}) "
            f"VALUES (?, ?, {placeholders})"
        )
        cursor.execute(
            sql,
            [context_id, timetag]
            + [values_by_field[column] for column in columns],
        )

    def _insert_syssetting_if_missing(
        self, cursor, context_id: str, timetag: datetime
    ):
        if self._record_exists(cursor, "SYSSETTING", context_id):
            return

        sql = (
            "INSERT INTO [SYSSETTING] "
            "(CONTEXTID, TIMETAG, TIME01, FIELD_1, FIELD_2, "
            "FIELD_3, FIELD_4, FIELD_6, FIELD_7) "
            "VALUES (?, ?, GETDATE(), ?, ?, NULL, NULL, 1, NULL)"
        )
        cursor.execute(
            sql,
            context_id,
            timetag,
            self.dispatch_config.factory_code,
            self.dispatch_config.system_type,
        )

    def _insert_legacy_related(
        self, cursor, context_id, timetag, context, payload
    ):
        """dispatch 未啟用時，保留原本逐筆建立兩張附屬表的行為。"""
        cursor.execute(
            "INSERT INTO [METROLOGY] "
            "(CONTEXTID, TIMETAG, FIELD_1, FIELD_2) VALUES (?, ?, ?, ?)",
            context_id,
            timetag,
            payload.get("compressor_energy_consumption"),
            payload.get("area_entrance_instant_flow"),
        )
        cursor.execute(
            "INSERT INTO [SYSSETTING] "
            "(CONTEXTID, TIMETAG, TIME01, FIELD_1, FIELD_2, FIELD_3, "
            "FIELD_4, FIELD_6, FIELD_7) "
            "VALUES (?, ?, GETDATE(), ?, ?, ?, ?, 1, NULL)",
            context_id,
            timetag,
            context.factory_code,
            context.system_type,
            context.equipment_type,
            context.machine_id,
        )

    def _keepalive(self):
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
                if time.monotonic() - self._last_keepalive >= KEEPALIVE_INTERVAL:
                    self._keepalive()
                continue

            try:
                self._insert(
                    item["table"], item["payload"], item.get("context")
                )
                self._last_keepalive = time.monotonic()
            except pyodbc.Error as e:
                sqlstate = e.args[0] if e.args else ""
                if sqlstate == "23000":
                    self.logger.debug(f"Duplicate/integrity record skipped: {e}")
                else:
                    self.logger.error(
                        f"DB insert error: {e} (data saved in raw_json)"
                    )
                    self._conn = None
            except Exception as e:
                self.logger.error(f"Unexpected DB error: {e}")
            finally:
                self.msg_queue.task_done()
