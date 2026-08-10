import queue
import signal
import threading

from aggregator import DataAggregator
from config_loader import ConfigLoader
from logger import setup_logger
from mqtt_receiver import MQTTReceiver
from raw_json_writer import RawJsonWriter


class App:
    """組裝並管理 MQTT → Queue → SQL Server 的所有元件。"""

    def __init__(self):
        # 載入連線、topic/table 對應及 JSON key/DB 欄位映射。
        loader = ConfigLoader()
        self.config, self.field_mapping = loader.load()

        self.logger = setup_logger(self.config.log.dir, self.config.log.level)
        self.logger.info("Initializing MQTT-SQL Bridge")

        # MQTT callback 不直接寫 DB；先進 Queue，避免 DB 延遲阻塞收訊。
        self.msg_queue = queue.Queue(maxsize=self.config.queue_maxsize)
        self.raw_json_writer = RawJsonWriter(self.config.raw_json.dir, self.logger)
        self.aggregator = DataAggregator(
            self.config.sampling_interval_seconds, self.msg_queue, self.logger
        )
        self.mqtt_receiver = MQTTReceiver(
            self.config.mqtt,
            self.aggregator,
            self.raw_json_writer,
            self.logger,
            db_enabled=self.config.db.enabled,
        )
        self.db_writer = None
        if self.config.db.enabled:
            # 測試訂閱模式不匯入 pyodbc，也不建立 DBWriter。
            from db_writer import DBWriter

            self.db_writer = DBWriter(
                self.config.db,
                self.config.dispatch,
                self.field_mapping,
                self.msg_queue,
                self.logger,
            )

    def start(self):
        # 先啟動資料庫消費端，再開始接收 MQTT，降低啟動時塞車機率。
        if self.db_writer:
            self.db_writer.start()
        else:
            self.logger.warning(
                "DB writing disabled: MQTT messages will only be saved to raw_json"
            )
        self.aggregator.start()
        self.mqtt_receiver.start()
        self.logger.info("Bridge running. Send SIGINT or SIGTERM to stop.")

    def stop(self):
        self.logger.info("Shutting down bridge...")
        # 先停止新資料進入，再讓聚合器送出尚未 flush 的資料。
        self.mqtt_receiver.stop()
        self.aggregator.stop()          # flush 剩餘緩衝資料
        if self.db_writer:
            self.logger.info("Waiting for queue to drain...")
            # 等 DBWriter 對 Queue 中每筆資料呼叫 task_done() 後才關閉連線。
            self.msg_queue.join()
            self.db_writer.stop()
        self.raw_json_writer.close()
        self.logger.info("Bridge stopped cleanly.")


def main():
    app = App()
    stop_event = threading.Event()

    def handle_signal(sig, frame):
        # Docker stop 會送 SIGTERM；本機 Ctrl+C 則是 SIGINT。
        app.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    app.start()
    stop_event.wait()


if __name__ == "__main__":
    main()
