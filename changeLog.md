# 2026-08-10

## MQTT 測試模式

- 新增 `db.enabled` 設定；停用時只接收 MQTT 與保存 JSONL，不載入 PyODBC、不連線 SQL Server，也不將資料放入 DB Queue。
- MQTT 測試模式會在 log 顯示收到的 topic 與目標 table。
- raw JSON 新增 `received_at`，用來比較設備 Timestamp 與 Parser 實際接收時間。

## CONTEXTID 與 dispatch

- 七張 PROCESS 表使用 `Factory_Code_System_Type_yyyyMMddHHmmss` 共用 CONTEXTID。
- 目前共用值設定為 `zhongli-A8_TecoS1_<Timestamp>`，同秒資料產生相同 ID。
- 修改前的完整 CONTEXTID 保存至來源表 `FIELD_20`。
- 支援 payload 使用 `Timestamp` 或 `timestamp`。
- 新增三表 dispatch：`PROCESS_BSAV55A`、`PROCESS_SA37`、`PROCESS_SA37XV` 具有相同 CONTEXTID 後，才建立 `METROLOGY` 與 `SYSSETTING`。
- 三張來源表的 `FIELD_2` 依 YAML 設定映射至 `METROLOGY.FIELD_1`～`FIELD_3`。
- `SYSSETTING.FIELD_2` 固定使用 `TecoS1`。
- PROCESS、METROLOGY、SYSSETTING 改為同一 transaction，任一失敗即 rollback。
- 新增動態 SQL table/column 識別字驗證。

## Schema 與測試

- 新增 `schema_dispatch_migration.sql`，用於補上七張 PROCESS 表的 `FIELD_20` 與 `METROLOGY.FIELD_3`。
- 新增 `test_db_writer.py`，驗證新舊 ID、三表到齊條件及 METROLOGY 欄位映射。
- 新增 `_excel_build` 測試工具，可把 JSONL 轉成七張 PROCESS、一張 METROLOGY、一張 SYSSETTING 工作表。
- 12 分鐘真實 MQTT 測試共接收 4,904 筆，三表同秒交集 574 組、七表同秒交集 516 組，同表同秒重複為 0。

## 已知事項

- 真實資料的相同設備 Timestamp 約相隔 111～144 秒才全部抵達 Parser，dispatch 必須保留未配對資料。
- `PROCESS_SA37.FIELD_2` 在本次真實資料中為空值，正式啟用 DB 前需確認 `METROLOGY.FIELD_2` 的正確來源欄位。
- `config.yaml` 含環境連線資訊，維持不納入版本控制；可提交的設定範例在 `config.yaml.example`。
