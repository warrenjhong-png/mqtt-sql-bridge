import queue
import signal
import threading

from aggregator import DataAggregator
from config_loader import ConfigLoader
from db_writer import DBWriter
from logger import setup_logger
from mqtt_receiver import MQTTReceiver
from raw_json_writer import RawJsonWriter


class App:
    def __init__(self):
        loader = ConfigLoader()
        self.config, self.field_mapping = loader.load()

        self.logger = setup_logger(self.config.log.dir, self.config.log.level)
        self.logger.info("Initializing MQTT-SQL Bridge")

        self.msg_queue = queue.Queue(maxsize=self.config.queue_maxsize)
        self.raw_json_writer = RawJsonWriter(self.config.raw_json.dir, self.logger)
        self.aggregator = DataAggregator(
            self.config.sampling_interval_seconds, self.msg_queue, self.logger
        )
        self.mqtt_receiver = MQTTReceiver(
            self.config.mqtt, self.aggregator, self.raw_json_writer, self.logger
        )
        self.db_writer = DBWriter(
            self.config.db, self.field_mapping, self.msg_queue, self.logger
        )

    def start(self):
        self.db_writer.start()
        self.aggregator.start()
        self.mqtt_receiver.start()
        self.logger.info("Bridge running. Send SIGINT or SIGTERM to stop.")

    def stop(self):
        self.logger.info("Shutting down bridge...")
        self.mqtt_receiver.stop()
        self.aggregator.stop()          # flush 剩餘緩衝資料
        self.logger.info("Waiting for queue to drain...")
        self.msg_queue.join()
        self.db_writer.stop()
        self.raw_json_writer.close()
        self.logger.info("Bridge stopped cleanly.")


def main():
    app = App()
    stop_event = threading.Event()

    def handle_signal(sig, frame):
        app.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    app.start()
    stop_event.wait()


if __name__ == "__main__":
    main()
