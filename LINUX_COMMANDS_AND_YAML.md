# Linux Docker 指令與 YAML 設定說明

## 一、部署指令

### 1. 解壓縮發行包

```bash
mkdir -p ~/mqtt-sql-bridge
tar -xzf mqtt-sql-bridge-linux-20260914.tar.gz \
  -C ~/mqtt-sql-bridge --strip-components=1
cd ~/mqtt-sql-bridge
```

### 2. 建立資料目錄並保護設定檔

```bash
mkdir -p logs raw_json
chmod 600 config.yaml
```

### 3. 建立並啟動容器

```bash
docker compose build --pull
docker compose up -d
```

### 4. 確認運行狀態

```bash
docker compose ps
docker compose logs --tail=100
docker compose logs -f
```

在 `logs -f` 畫面按 `Ctrl+C` 只會停止觀看，不會停止容器。

### 5. 常用管理指令

```bash
# 重新啟動
docker compose restart

# 停止但保留容器
docker compose stop

# 再次啟動
docker compose start

# 停止並移除容器，主機上的設定、logs、raw_json 仍保留
docker compose down

# 重新建置並啟動
docker compose up -d --build

# 查看最近 200 行
docker compose logs --tail=200

# 查看容器資源使用量
docker stats mqtt_sql_bridge

# 查看容器實際掛載
docker inspect mqtt_sql_bridge --format '{{json .Mounts}}'
```

### 6. 檢查保存資料

```bash
ls -lh logs
ls -lh raw_json
tail -n 50 logs/bridge.log
tail -n 3 raw_json/$(date +%F).jsonl
```

### 7. 檢查網路連線

```bash
# MQTT；將 IP 換成 config.yaml 的 broker
nc -vz MQTT_BROKER_IP 1883

# SQL Server；將 IP 換成 config.yaml 的 server
nc -vz SQL_SERVER_IP 1433

# Dispatch；將網址換成實際 API URL
curl -v 'http://DISPATCH_SERVER/SICApi/sic/GetDispatch?dispatchName=X&command=test40'
```

若 Linux 沒有 `nc`：

```bash
sudo apt-get update
sudo apt-get install -y netcat-openbsd curl
```

## 二、docker-compose.yml

此檔案定義容器名稱、重新啟動策略及主機目錄掛載：

```yaml
services:
  mqtt-sql-bridge:
    build: .
    container_name: mqtt_sql_bridge
    restart: always
    volumes:
      - ./logs:/app/logs
      - ./raw_json:/app/raw_json
      - ./config.yaml:/app/config.yaml:ro
      - ./field_mapping.yaml:/app/field_mapping.yaml:ro
    environment:
      - TZ=Asia/Taipei
```

- `build: .`：使用目前目錄的 `Dockerfile` 建立 image。
- `container_name`：Docker 容器名稱；同一台主機不可重複。
- `restart: always`：Docker Engine 啟動後自動恢復容器。
- `./logs`、`./raw_json`：相對於 `docker-compose.yml` 所在目錄。
- `:ro`：容器只能讀取 YAML，不能修改主機設定檔。
- 本服務不需開放對外 port，因為它主動連線 MQTT、SQL Server 與 Dispatch API。

## 三、config.yaml

### MQTT 設定

```yaml
mqtt:
  broker: "192.168.1.10"
  port: 1883
  username: "mqtt_user"
  password: "mqtt_password"
  client_id: "mqtt_sql_bridge_linux_01"
  keepalive: 60
  reconnect_delay: 10
  topics:
    - topic: "factory/compressor/c1/telemetry"
      table: "PROCESS_SA37XV"
      context:
        factory_code: "zhongli-A8"
        system_type: "PROCESS"
        equipment_type: "SA37XV"
        machine_id: "C1"
```

- `client_id` 必須在同一 MQTT Broker 上保持唯一；重複會導致兩個 Client 互踢、反覆斷線。
- `topic` 必須與 MQTT 發送端完全一致。
- `table` 是寫入的 SQL Server 資料表。
- `context` 用於產生 CONTEXTID 與設備識別資料。

### DB 設定

```yaml
db:
  enabled: true
  server: "192.168.1.20"
  database: "TECO_AVM3_STDB_Warren"
  username: "db_user"
  password: "db_password"
  driver: "ODBC Driver 18 for SQL Server"
  reconnect_delay: 5
```

- `enabled: true`：接收 MQTT 並寫入 SQL Server。
- `enabled: false`：只測試 MQTT 與 raw JSON，不連線、不寫入 DB。
- `server`：填 SQL Server IP 或 DNS 名稱，不要填 Docker 容器自己的 `127.0.0.1`。

### Dispatch 設定

```yaml
dispatch:
  enabled: true
  factory_code: "zhongli-A8"
  system_type: "TecoS1"
  batch_size: 40
  dispatch_x:
    enabled: true
    url: "http://192.168.1.30/SICApi/sic/GetDispatch?dispatchName=X&command=PieceId"
  dispatch_y:
    enabled: true
    url: "http://192.168.1.30/SICApi/sic/GetDispatch?dispatchName=Y&command=PieceId"
  sources:
    - table: "PROCESS_BSAV55A"
      source_field: "FIELD_2"
      target_field: "FIELD_1"
    - table: "PROCESS_SA37"
      source_field: "FIELD_2"
      target_field: "FIELD_2"
    - table: "PROCESS_SA37XV"
      source_field: "FIELD_2"
      target_field: "FIELD_3"
```

- `dispatch.enabled`：Dispatch 總開關。
- `batch_size: 40`：累積 40 個完成三表配對的 CONTEXTID 後，只用第 40 個 ID 呼叫 X、Y 各一次；設為 `1` 代表每筆發送。
- URL 中的 `command=PieceId` 是預留值，送出前會動態替換成該批第 N 筆 CONTEXTID。
- X、Y 各有獨立 `enabled` 與 `url`。
- 三張來源表在同一秒完成配對並成功 commit DB 後，才進入 Dispatch 批次。
- Dispatch API 在其他主機時，URL 必須使用容器可連線的 IP/DNS，不能使用 `127.0.0.1`。

### Log、raw JSON 與 Queue

```yaml
log:
  dir: "logs"
  level: "INFO"

raw_json:
  dir: "raw_json"

queue_maxsize: 10000
sampling_interval_seconds: 0
```

- `raw_json` 在 DB 寫入前保存收到的合法 MQTT JSON。
- `queue_maxsize` 是記憶體佇列上限；滿載時新訊息會被捨棄並留下警告。
- `sampling_interval_seconds: 0` 表示每筆通過；大於 0 表示依指定秒數彙整。

## 四、field_mapping.yaml

此檔案將 SQL 欄位對應到 MQTT JSON key：

```yaml
FIELD_1: compressor_drive_type
FIELD_2: area_entrance_instant_flow
FIELD_3: area_entrance_gas_pressure
```

左側是 SQL Server 欄位，右側是 payload 的 JSON key。修改後需重新啟動容器：

```bash
docker compose restart
docker compose logs --tail=100
```

## 五、更新前備份

```bash
cp config.yaml config.yaml.$(date +%Y%m%d_%H%M%S).backup
cp field_mapping.yaml field_mapping.yaml.$(date +%Y%m%d_%H%M%S).backup
```

更新程式檔後：

```bash
docker compose up -d --build
docker compose logs --tail=100
```
