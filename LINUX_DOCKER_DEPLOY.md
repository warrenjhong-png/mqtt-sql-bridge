# MQTT SQL Bridge — Linux Docker 部署

本發行包適用於 x86_64 Linux，主機需先安裝 Docker Engine 與 Docker Compose Plugin。

完整的日常操作指令與各 YAML 欄位說明，請參閱 `LINUX_COMMANDS_AND_YAML.md`。

## 1. 解壓縮

```bash
mkdir -p ~/mqtt-sql-bridge
tar -xzf mqtt-sql-bridge-linux-20260914.tar.gz -C ~/mqtt-sql-bridge
cd ~/mqtt-sql-bridge
```

## 2. 檢查設定

部署前請編輯同一目錄內的 `config.yaml`：

- `mqtt.broker`、帳號、密碼與 `client_id`
- `mqtt.topics` 的 topic、資料表及 context
- `db.enabled` 與 SQL Server 連線資訊
- `dispatch.enabled`、`dispatch.batch_size`
- `dispatch.dispatch_x.url`、`dispatch.dispatch_y.url`

若 Dispatch API 位於另一台主機，URL 不可使用 `127.0.0.1`；請填入該 API 主機可由 Docker 容器連線的 IP 或 DNS 名稱。

## 3. 建立並啟動

```bash
mkdir -p logs raw_json
docker compose build --pull
docker compose up -d
```

## 4. 確認狀態

```bash
docker compose ps
docker compose logs --tail=100
docker compose logs -f
```

正常情況會看到 MQTT connected、Subscribed 與 DB connected。按 `Ctrl+C` 只會離開 log 畫面，不會停止容器。

## 5. 停止與重新啟動

```bash
docker compose stop
docker compose start
docker compose restart
```

需要移除容器但保留 `logs`、`raw_json` 與設定檔時：

```bash
docker compose down
```

## 6. 更新版本

先備份 `config.yaml`，再以新發行包覆蓋程式檔，最後重新建立：

```bash
cp config.yaml config.yaml.backup
docker compose up -d --build
docker compose logs --tail=100
```

## 注意事項

- `config.yaml` 含 MQTT、SQL Server 等連線資訊，請限制檔案權限：`chmod 600 config.yaml`。
- `logs/` 與 `raw_json/` 透過相對路徑掛載，資料會保存在本部署目錄中。
- Compose 設定為 `restart: always`；Docker 服務隨系統啟動後，容器會自動恢復。
- 請勿在同一台 Docker 主機重複使用 `mqtt_sql_bridge` 容器名稱。
