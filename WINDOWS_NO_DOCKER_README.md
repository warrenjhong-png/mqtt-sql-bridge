# Windows 非 Docker 部署

1. 安裝 Python 3.11 或 3.12（64-bit），安裝時勾選 `Add Python to PATH`。
2. 安裝 Microsoft ODBC Driver 18 for SQL Server。
3. 先檢查 `config.yaml` 的 MQTT、SQL Server 與 Dispatch API 設定。
4. 雙擊 `install_windows.bat` 建立 `.venv` 並安裝 Python 套件。
5. 雙擊 `start_parser.bat` 啟動 Parser。
6. 停止時在視窗按 `Ctrl+C`。

## Dispatch URL

非 Docker 模式不要使用 `host.docker.internal`。API 若在同一台電腦，使用 `localhost`；若在其他電腦，使用該電腦的 IP。

例如：

```yaml
dispatch_x:
  enabled: true
  url: "http://140.116.234.108:41088/SICApi/sic/GetDispatch?dispatchName=X&command=PieceId"
dispatch_y:
  enabled: true
  url: "http://140.116.234.108:41088/SICApi/sic/GetDispatch?dispatchName=Y&command=PieceId"
```

正式切換前請先停止舊電腦上的 Parser，避免兩支程式同時寫入資料庫。
