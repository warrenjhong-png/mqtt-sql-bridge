import logging
import queue
import sys
import types
import unittest
from datetime import datetime


# 測試不需要真正連線 DB；未安裝 pyodbc 時提供最小替身供模組載入。
if "pyodbc" not in sys.modules:
    pyodbc_stub = types.ModuleType("pyodbc")
    pyodbc_stub.Error = Exception
    sys.modules["pyodbc"] = pyodbc_stub

from db_writer import DBWriter


class Object:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeCursor:
    def __init__(self, source_values):
        self.source_values = source_values
        self.last_row = None
        self.inserts = []

    def execute(self, sql, *params):
        if sql.startswith("SELECT TOP 1 [FIELD_2] FROM"):
            table = sql.split("FROM [", 1)[1].split("]", 1)[0]
            value = self.source_values.get(table)
            self.last_row = None if value is None else (value,)
        elif sql.startswith("SELECT TOP 1 1 FROM"):
            self.last_row = None
        elif sql.startswith("INSERT INTO"):
            self.inserts.append((sql, params))
            self.last_row = None
        return self

    def fetchone(self):
        return self.last_row


def make_writer():
    sources = [
        Object(
            table="PROCESS_BSAV55A",
            source_field="FIELD_2",
            target_field="FIELD_1",
        ),
        Object(
            table="PROCESS_SA37",
            source_field="FIELD_2",
            target_field="FIELD_2",
        ),
        Object(
            table="PROCESS_SA37XV",
            source_field="FIELD_2",
            target_field="FIELD_3",
        ),
    ]
    return DBWriter(
        Object(driver="", server="", database="", username="", password=""),
        Object(
            enabled=True,
            factory_code="zhongli-A8",
            system_type="TecoS1",
            sources=sources,
        ),
        {"FIELD_1": "compressor_drive_type"},
        queue.Queue(),
        logging.getLogger("test"),
    )


class DBWriterTests(unittest.TestCase):
    def test_shared_and_original_context_ids(self):
        writer = make_writer()
        timestamp = datetime.fromisoformat("2026-07-08T14:46:39+08:00")
        context = Object(
            factory_code="zhongli-C21",
            system_type="PROCESS",
            equipment_type="BSAV55A",
            machine_id="c3",
        )
        payload = {"compressor_drive_type": "VSD"}

        self.assertEqual(
            writer._build_context_id(context, timestamp),
            "zhongli-A8_TecoS1_20260708144639",
        )
        self.assertEqual(
            writer._build_original_context_id(context, payload, timestamp),
            "zhongli-C21_PROCESS_BSAV55A_c3_VSD_20260708144639",
        )

    def test_dispatch_waits_until_all_three_sources_exist(self):
        writer = make_writer()
        cursor = FakeCursor(
            {"PROCESS_BSAV55A": 10.0, "PROCESS_SA37": 20.0}
        )

        writer._dispatch_if_ready(
            cursor,
            "zhongli-A8_TecoS1_20260708144639",
            datetime(2026, 7, 8, 14, 46, 39),
        )

        self.assertEqual(cursor.inserts, [])

    def test_dispatch_maps_source_field_2_to_metrology_fields(self):
        writer = make_writer()
        cursor = FakeCursor(
            {
                "PROCESS_BSAV55A": 10.0,
                "PROCESS_SA37": 20.0,
                "PROCESS_SA37XV": 30.0,
            }
        )

        writer._dispatch_if_ready(
            cursor,
            "zhongli-A8_TecoS1_20260708144639",
            datetime(2026, 7, 8, 14, 46, 39),
        )

        self.assertEqual(len(cursor.inserts), 2)
        metrology_sql, metrology_params = cursor.inserts[0]
        self.assertIn("[FIELD_1], [FIELD_2], [FIELD_3]", metrology_sql)
        self.assertEqual(list(metrology_params[0][-3:]), [10.0, 20.0, 30.0])
        self.assertIn("INSERT INTO [SYSSETTING]", cursor.inserts[1][0])


if __name__ == "__main__":
    unittest.main()
