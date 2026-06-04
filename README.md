# MQTT → SQL Server Bridge

空壓機資料收集服務。訂閱 MQTT topic，將 JSON 感測資料寫入 SQL Server，並在本機保存原始 jsonl 備份。

## 架構

```
MQTT Broker
    │
    ▼
MQTTReceiver (paho-mqtt, loop_start)
    │  ├─► RawJsonWriter → raw_json/YYYY-MM-DD.jsonl
    │
    ▼
Queue (buffer, maxsize=10000)
    │
    ▼
DBWriter (worker thread)
    │
    ▼
SQL Server
```

## 目錄結構

```
mqtt_sql_bridge/
├── main.py              進入點、graceful shutdown
├── mqtt_receiver.py     MQTT 訂閱、auto-reconnect
├── db_writer.py         DB worker thread、auto-reconnect
├── config_loader.py     載入 yaml 設定
├── raw_json_writer.py   本機 jsonl 日誌
├── logger.py            logging 設定
├── config.yaml          ← 修改此檔案來調整設定
├── field_mapping.yaml   ← 修改 FIELD 對應關係
├── Dockerfile
├── docker-compose.yml
├── logs/                自動建立
└── raw_json/            自動建立
```

## SQL Server Table 結構

```sql
CREATE TABLE CompressorData_01 (
    CONTEXTID   INT IDENTITY(1,1) PRIMARY KEY,
    TIMETAG     DATETIME DEFAULT GETDATE(),
    FIELD_1     FLOAT,
    FIELD_2     FLOAT,
    FIELD_3     FLOAT,
    FIELD_4     FLOAT,
    FIELD_5     FLOAT,
    FIELD_6     FLOAT,
    FIELD_7     FLOAT,
    FIELD_8     FLOAT,
    FIELD_9     FLOAT,
    FIELD_10    FLOAT,
    FIELD_11    FLOAT,
    FIELD_12    FLOAT,
    FIELD_13    FLOAT,
    FIELD_14    FLOAT,
    FIELD_15    NVARCHAR(50)  -- device timestamp
);
```

## 設定

**config.yaml** — 修改 MQTT broker IP、SQL Server 連線資訊、topic/table 對應：

```yaml
mqtt:
  broker: "192.168.1.100"   # MQTT broker IP
  topics:
    - topic: "factory/compressor/01"
      table: "CompressorData_01"

db:
  server: "192.168.1.200"
  database: "FactoryDB"
  username: "sa"
  password: "your_password"
```

**field_mapping.yaml** — FIELD 欄位與 JSON key 的對應，不需動程式碼：

```yaml
FIELD_1: area_entrance_instant_flow
FIELD_15: timestamp
```

## 部署（Docker）

```bash
# 建立 image
docker-compose build

# 啟動（背景、開機自啟）
docker-compose up -d

# 查看即時 log
docker-compose logs -f

# 停止
docker-compose down
```

## 本機直接執行（開發測試）

```bash
pip install -r requirements.txt
python main.py
```

停止：`Ctrl+C`

## 測試

使用 `mosquitto_pub` 發送測試資料：

```bash
mosquitto_pub -h 192.168.1.100 -t "factory/compressor/01" -m '{
  "timestamp": "2026-06-01T15:46:00+08:00",
  "area_entrance_instant_flow": 120.5,
  "area_entrance_gas_pressure": 0.65,
  "compressor_outlet_instant_flow": 115.2,
  "compressor_outlet_pressure": 0.72,
  "air_tank_pressure": 0.68,
  "compressor_pressure_set_point": 0.75,
  "vfd_motor_frequency": 45.0,
  "compressor_inlet_temp": 28.5,
  "compressor_outlet_temp": 75.3,
  "compressor_operating_temp": 68.1,
  "compressor_energy_consumption": 14520.8,
  "compressor_power": 18.1,
  "compressor_input_current": 32.4,
  "compressor_input_voltage": 380.0
}'
```

確認：
1. `raw_json/YYYY-MM-DD.jsonl` 有新增一行
2. SQL Server `CompressorData_01` 有新增一筆資料
3. `logs/bridge.log` 無 ERROR

## 新增第二、三台機器

只需修改 `config.yaml`，新增 topic/table 對應即可，不需改程式碼：

```yaml
mqtt:
  topics:
    - topic: "factory/compressor/01"
      table: "CompressorData_01"
    - topic: "factory/compressor/02"   # 新增
      table: "CompressorData_02"
```
