import json
import logging

import paho.mqtt.client as mqtt

from aggregator import DataAggregator
from raw_json_writer import RawJsonWriter


class MQTTReceiver:
    """接收 MQTT 訊息，保存原始 JSON，再交給聚合器處理。"""

    def __init__(
        self,
        mqtt_config,
        aggregator: DataAggregator,
        raw_json_writer: RawJsonWriter,
        logger: logging.Logger,
        db_enabled: bool = True,
    ):
        self.mqtt_config = mqtt_config
        self.aggregator = aggregator
        self.raw_json_writer = raw_json_writer
        self.logger = logger
        self.db_enabled = db_enabled

        # 收到訊息時，以 topic 快速查到目標 SQL table 與設備 context。
        self._topic_map = {tm.topic: tm for tm in mqtt_config.topics}

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=mqtt_config.client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        if mqtt_config.username:
            self._client.username_pw_set(mqtt_config.username, mqtt_config.password)

    def start(self):
        # connect_async 搭配 loop_start，網路處理由 Paho 背景執行緒負責。
        self._client.reconnect_delay_set(
            min_delay=1, max_delay=self.mqtt_config.reconnect_delay
        )
        self._client.connect_async(
            self.mqtt_config.broker,
            self.mqtt_config.port,
            self.mqtt_config.keepalive,
        )
        self._client.loop_start()
        self.logger.info(
            f"MQTTReceiver started, connecting to {self.mqtt_config.broker}"
        )

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()
        self.logger.info("MQTTReceiver stopped")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.info(
                f"MQTT connected to {self.mqtt_config.broker}:"
                f"{self.mqtt_config.port}"
            )
            for tm in self.mqtt_config.topics:
                # QoS 1 是「至少一次」，下游可能遇到重複訊息。
                client.subscribe(tm.topic, qos=1)
                self.logger.info(f"Subscribed: {tm.topic} → {tm.table}")
        else:
            self.logger.warning(f"MQTT connect failed, rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning(
                f"MQTT disconnected unexpectedly (rc={rc}), auto-reconnecting..."
            )

    def _on_message(self, client, userdata, msg):
        """Paho 收到訊息時呼叫；此處應保持快速以免阻塞後續收訊。"""
        try:
            # topic 決定 table；payload 本身不能指定 SQL table。
            tm = self._topic_map.get(msg.topic)
            if not tm:
                self.logger.warning(f"Unknown topic: {msg.topic}")
                return

            if not msg.payload:
                self.logger.warning(
                    f"Empty payload on topic: {msg.topic}, skipped"
                )
                return

            # MQTT payload 是 bytes，先用 UTF-8 解碼，再解析為 dict。
            payload = json.loads(msg.payload.decode("utf-8"))

            # DB 是否啟用都先保存原始 JSON，方便驗證訂閱結果。
            self.raw_json_writer.write(tm.table, payload)

            if self.db_enabled:
                # 正常模式：交給聚合器，稍後由 DBWriter 寫入 SQL Server。
                self.aggregator.ingest(tm.table, payload, tm.context)
            else:
                # MQTT 測試模式：不送入 Queue，也不會寫入 DB。
                self.logger.info(
                    f"MQTT test mode received: topic={msg.topic}, table={tm.table}"
                )

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e} | raw: {msg.payload}")
        except Exception as e:
            self.logger.error(f"on_message error: {e}")
