import json
import logging
import queue
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch


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
            batch_size=1,
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
        syssetting_sql, syssetting_params = cursor.inserts[1]
        self.assertIn("INSERT INTO [SYSSETTING]", syssetting_sql)
        self.assertIn("FIELD_7", syssetting_sql)
        self.assertEqual(syssetting_params[-1], "IN_FLOW_FORECAST")

    def test_legacy_syssetting_sets_field_7_to_in_flow_forecast(self):
        writer = make_writer()
        cursor = FakeCursor({})
        context = Object(
            factory_code="zhongli-C21",
            system_type="PROCESS",
            equipment_type="BSAV55A",
            machine_id="c3",
        )

        writer._insert_legacy_related(
            cursor,
            "legacy-context-id",
            datetime(2026, 9, 30, 12, 0, 0),
            context,
            {},
        )

        syssetting_sql, syssetting_params = cursor.inserts[1]
        self.assertIn("FIELD_7", syssetting_sql)
        self.assertEqual(syssetting_params[-1], "IN_FLOW_FORECAST")

    @patch("db_writer.urlopen")
    def test_sends_dispatch_x_and_y_with_context_id(self, mock_urlopen):
        writer = make_writer()
        writer.dispatch_config.dispatch_x = Object(
            enabled=True,
            url="http://host.docker.internal/SICApi/sic/GetDispatch?dispatchName=X&command=PieceId",
        )
        writer.dispatch_config.dispatch_y = Object(
            enabled=True,
            url="http://host.docker.internal/SICApi/sic/GetDispatch?dispatchName=Y&command=PieceId",
        )
        response = MagicMock()
        response.status = 200
        response.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = response

        context_id = "zhongli-A8_TecoS1_20260708144639"
        writer._send_web_dispatches(context_id)

        self.assertEqual(mock_urlopen.call_count, 2)
        requests = [call.args[0] for call in mock_urlopen.call_args_list]
        self.assertIn(
            "dispatchName=X&command=zhongli-A8_TecoS1_20260708144639",
            requests[0].full_url,
        )
        self.assertIn(
            "dispatchName=Y&command=zhongli-A8_TecoS1_20260708144639",
            requests[1].full_url,
        )
        for request in requests:
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Content-type"), "application/json")

        self.assertEqual(
            json.loads(requests[0].data.decode("utf-8")),
            {
                "dispatchName": "X",
                "command": context_id,
            },
        )
        self.assertEqual(
            json.loads(requests[1].data.decode("utf-8")),
            {
                "dispatchName": "Y",
                "command": context_id,
            },
        )

    def test_waits_until_batch_size_then_sends_only_last_context_id(self):
        writer = make_writer()
        writer._dispatch_batch_size = 3
        writer._send_web_dispatches = MagicMock()
        context_ids = ["context-1", "context-2", "context-3"]

        writer._queue_web_dispatch(context_ids[0])
        writer._queue_web_dispatch(context_ids[1])
        writer._send_web_dispatches.assert_not_called()

        writer._queue_web_dispatch(context_ids[2])

        writer._send_web_dispatches.assert_called_once_with("context-3")

    def test_does_not_count_duplicate_context_id_twice(self):
        writer = make_writer()
        writer._dispatch_batch_size = 2
        writer._send_web_dispatches = MagicMock()

        writer._queue_web_dispatch("context-1")
        writer._queue_web_dispatch("context-1")
        writer._send_web_dispatches.assert_not_called()

        writer._queue_web_dispatch("context-2")
        writer._send_web_dispatches.assert_called_once_with("context-2")


if __name__ == "__main__":
    unittest.main()
