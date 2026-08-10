import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const inputPath = process.env.INPUT_PATH
  ? path.resolve(root, process.env.INPUT_PATH)
  : path.join(root, "raw_json", "2026-08-05.jsonl");
const outputDir = process.env.OUTPUT_DIR
  ? path.resolve(root, process.env.OUTPUT_DIR)
  : path.join(root, "outputs", "topic-excel-test");
const outputName = process.env.OUTPUT_NAME ?? "mqtt_topic_rule_test_2026-08-05.xlsx";
const outputPath = path.join(outputDir, outputName);

const tableContexts = {
  PROCESS_SA37XV: ["zhongli-G8", "PROCESS", "SA37XV", "c2"],
  PROCESS_BSAV55A: ["zhongli-C21", "PROCESS", "BSAV55A", "c3"],
  PROCESS_SA37: ["zhongli-B21", "PROCESS", "SA37", "c4"],
  PROCESS_G8_SA475: ["zhongli-G8", "PROCESS", "G8-SA475", "c1"],
  PROCESS_B21_SA475: ["zhongli-B21", "PROCESS", "B21-SA475", "c5"],
  PROCESS_A8_SA55W: ["zhongli-A8", "PROCESS", "A8-SA55W", "c6"],
  Process_Zone3: ["zhongli-Zone3", "PROCESS", "Zone3", "xx"],
};

const fieldMap = {
  FIELD_1: "compressor_drive_type",
  FIELD_2: "area_entrance_instant_flow",
  FIELD_3: "area_entrance_gas_pressure",
  FIELD_4: "compressor_outlet_instant_flow",
  FIELD_5: "compressor_outlet_pressure",
  FIELD_6: "air_tank_pressure",
  FIELD_7: "compressor_unload_pressure",
  FIELD_8: "compressor_load_pressure",
  FIELD_9: "compressor_vsd_target_pressure",
  FIELD_10: "vfd_motor_frequency",
  FIELD_11: "compressor_inlet_temp",
  FIELD_12: "compressor_outlet_temp",
  FIELD_13: "compressor_operating_temp",
  FIELD_14: "compressor_energy_consumption",
  FIELD_15: "compressor_power",
  FIELD_16: "compressor_input_current",
  FIELD_17: "compressor_input_voltage",
};

const processTables = Object.keys(tableContexts);
const dispatchTables = ["PROCESS_BSAV55A", "PROCESS_SA37", "PROCESS_SA37XV"];
const processHeaders = [
  "CONTEXTID", "TIMETAG", "TIME01",
  ...Array.from({ length: 20 }, (_, i) => `FIELD_${i + 1}`),
];

function parseTime(payload) {
  const text = payload.Timestamp ?? payload.timestamp;
  const date = text ? new Date(text) : new Date();
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function excelWallTimeText(text) {
  const match = typeof text === "string"
    ? text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
    : null;
  if (!match) return new Date();
  // Excel 儲存的是無時區日期；用 UTC 建構可保留 MQTT 畫面上的台北時間。
  return new Date(Date.UTC(
    Number(match[1]), Number(match[2]) - 1, Number(match[3]),
    Number(match[4]), Number(match[5]), Number(match[6]),
  ));
}

function excelWallTime(payload) {
  return excelWallTimeText(payload.Timestamp ?? payload.timestamp);
}

function serial(date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}${get("month")}${get("day")}${get("hour")}${get("minute")}${get("second")}`;
}

function sharedId(date) {
  return `zhongli-A8_TecoS1_${serial(date)}`;
}

function originalId(table, payload, date) {
  const [factory, system, equipment, machine] = tableContexts[table];
  return `${factory}_${system}_${equipment}_${machine}_${payload.compressor_drive_type ?? ""}_${serial(date)}`;
}

const text = await fs.readFile(inputPath, "utf8");
const records = text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
const byTable = Object.fromEntries(processTables.map((table) => [table, []]));

for (const record of records) {
  if (!byTable[record.table]) continue;
  const payload = record.payload ?? {};
  const sourceTime = parseTime(payload);
  const timetag = excelWallTime(payload);
  const receivedAt = excelWallTimeText(record.received_at);
  const fields = Array.from({ length: 20 }, () => null);
  for (const [field, key] of Object.entries(fieldMap)) {
    fields[Number(field.split("_")[1]) - 1] = payload[key] ?? null;
  }
  fields[19] = originalId(record.table, payload, sourceTime);
  byTable[record.table].push({
    contextId: sharedId(sourceTime),
    timetag,
    receivedAt,
    fields,
  });
}

const sourceById = Object.fromEntries(dispatchTables.map((table) => [table, new Map()]));
for (const table of dispatchTables) {
  for (const row of byTable[table]) {
    if (!sourceById[table].has(row.contextId)) sourceById[table].set(row.contextId, row);
  }
}

const dispatchIds = [...sourceById[dispatchTables[0]].keys()]
  .filter((id) => dispatchTables.every((table) => sourceById[table].has(id)))
  .sort();

const workbook = Workbook.create();
const headerFormat = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};

function styleSheet(sheet, rowCount, colCount) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const header = sheet.getRangeByIndexes(0, 0, 1, colCount);
  header.format = headerFormat;
  header.format.rowHeight = 26;
  const used = sheet.getRangeByIndexes(0, 0, Math.max(rowCount, 1), colCount);
  used.format.autofitColumns();
  used.format.autofitRows();
  sheet.getRange("A:A").format.columnWidth = 34;
  if (colCount > 1) sheet.getRange("B:C").format.columnWidth = 21;
  if (rowCount > 1) sheet.getRange(`B2:C${rowCount}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
}

for (const table of processTables) {
  const sheet = workbook.worksheets.add(table);
  const rows = byTable[table].map((row) => [
    row.contextId,
    row.timetag,
    row.receivedAt,
    ...row.fields,
  ]);
  sheet.getRangeByIndexes(0, 0, 1, processHeaders.length).values = [processHeaders];
  if (rows.length) {
    sheet.getRangeByIndexes(1, 0, rows.length, processHeaders.length).values = rows;
    sheet.tables.add(
      `A1:W${rows.length + 1}`,
      true,
      `${table.replace(/[^A-Za-z0-9]/g, "")}Table`,
    );
    sheet.getRange(`A2:A${rows.length + 1}`).conditionalFormats.add(
      "duplicateValues",
      {
        format: {
          fill: "#FDE9D9",
          font: { color: "#9C0006" },
        },
      },
    );
  }
  styleSheet(sheet, rows.length + 1, processHeaders.length);
}

const metrology = workbook.worksheets.add("METROLOGY");
const metrologyHeaders = ["CONTEXTID", "TIMETAG", "FIELD_1", "FIELD_2", "FIELD_3"];
const metrologyRows = dispatchIds.map((id) => {
  const sourceRows = dispatchTables.map((table) => sourceById[table].get(id));
  return [id, sourceRows[0].timetag, ...sourceRows.map((row) => row.fields[1])];
});
metrology.getRange("A1:E1").values = [metrologyHeaders];
if (metrologyRows.length) {
  metrology.getRangeByIndexes(1, 0, metrologyRows.length, 5).values = metrologyRows;
  metrology.tables.add(`A1:E${metrologyRows.length + 1}`, true, "MetrologyTable");
}
styleSheet(metrology, metrologyRows.length + 1, 5);
if (metrologyRows.length) {
  metrology.getRange(`C2:E${metrologyRows.length + 1}`).format.numberFormat = "0.###";
}

const syssetting = workbook.worksheets.add("SYSSETTING");
const settingHeaders = [
  "CONTEXTID", "TIMETAG", "TIME01", "FIELD_1", "FIELD_2",
  "FIELD_3", "FIELD_4", "FIELD_6", "FIELD_7",
];
const settingRows = dispatchIds.map((id) => [
  id,
  sourceById[dispatchTables[0]].get(id).timetag,
  new Date(Math.max(...dispatchTables.map(
    (table) => sourceById[table].get(id).receivedAt.getTime()
  ))),
  "zhongli-A8",
  "TecoS1",
  null,
  null,
  1,
  null,
]);
syssetting.getRange("A1:I1").values = [settingHeaders];
if (settingRows.length) {
  syssetting.getRangeByIndexes(1, 0, settingRows.length, 9).values = settingRows;
  syssetting.tables.add(`A1:I${settingRows.length + 1}`, true, "SyssettingTable");
}
styleSheet(syssetting, settingRows.length + 1, 9);

await fs.mkdir(outputDir, { recursive: true });
for (const sheetName of [...processTables, "METROLOGY", "SYSSETTING"]) {
  const preview = await workbook.render({
    sheetName,
    range: sheetName === "METROLOGY" ? "A1:E8" : sheetName === "SYSSETTING" ? "A1:I8" : "A1:W8",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(outputDir, `${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const inspection = await workbook.inspect({
  kind: "sheet,table",
  maxChars: 6000,
  tableMaxRows: 3,
  tableMaxCols: 8,
});
console.log(inspection.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);
console.log(JSON.stringify({ inputRecords: records.length, processCounts: Object.fromEntries(processTables.map((t) => [t, byTable[t].length])), dispatchCount: dispatchIds.length }));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
