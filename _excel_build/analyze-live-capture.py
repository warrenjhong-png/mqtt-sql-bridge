import collections
import datetime
import json
import statistics
import sys
from pathlib import Path


TABLES = [
    "PROCESS_SA37XV",
    "PROCESS_BSAV55A",
    "PROCESS_SA37",
    "PROCESS_G8_SA475",
    "PROCESS_B21_SA475",
    "PROCESS_A8_SA55W",
    "Process_Zone3",
]
DISPATCH_TABLES = ["PROCESS_BSAV55A", "PROCESS_SA37", "PROCESS_SA37XV"]


def parse(value):
    return datetime.datetime.fromisoformat(value)


records = {table: collections.defaultdict(list) for table in TABLES}
for line in Path(sys.argv[1]).open(encoding="utf-8"):
    record = json.loads(line)
    table = record.get("table")
    payload = record.get("payload", {})
    timestamp_text = payload.get("Timestamp") or payload.get("timestamp")
    received_text = record.get("received_at")
    if table not in records or not timestamp_text or not received_text:
        continue
    timestamp = parse(timestamp_text)
    received = parse(received_text)
    key = timestamp.strftime("%Y%m%d%H%M%S")
    records[table][key].append((timestamp, received, payload))

sets = {table: set(values) for table, values in records.items()}
three = set.intersection(*(sets[table] for table in DISPATCH_TABLES))
seven = set.intersection(*(sets[table] for table in TABLES))

print("counts", {table: sum(map(len, values.values())) for table, values in records.items()})
print("duplicate_seconds", {table: sum(len(rows) > 1 for rows in values.values()) for table, values in records.items()})
print("max_per_second", {table: max(map(len, values.values()), default=0) for table, values in records.items()})
print("three_table_matches", len(three))
print("seven_table_matches", len(seven))

if three:
    receive_spreads = []
    for key in three:
        times = [records[table][key][0][1] for table in DISPATCH_TABLES]
        receive_spreads.append((max(times) - min(times)).total_seconds())
    print(
        "three_match_receive_spread_seconds",
        {
            "min": min(receive_spreads),
            "median": statistics.median(receive_spreads),
            "max": max(receive_spreads),
        },
    )

for table in DISPATCH_TABLES:
    lags = []
    for rows in records[table].values():
        for timestamp, received, _ in rows:
            lags.append((received - timestamp).total_seconds())
    print(
        table,
        "receive_minus_device_seconds",
        {
            "min": min(lags),
            "median": statistics.median(lags),
            "max": max(lags),
        },
    )
