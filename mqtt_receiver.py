import json
import logging
from typing import Dict

import paho.mqtt.client as mqtt

from aggregator import DataAggregator
from raw_json_writer import RawJsonWriter


class MQTTReceiver:
    def __init__(
        self,
        mqtt_config,
        aggregator: DataAggregator,
        raw_json_writer: RawJsonWriter,
        logger: logging.Logger,
    ):
        self.mqtt_config = mqtt_config
        self.aggregator = aggregator
        self.raw_json_writer = raw_json_writer
        self.logger = logger

        self._topic_table_map: Dict[str, str] = {
            tm.topic: tm.table for tm in mqtt_config.topics
        }

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
        self._client.reconnect_delay_set(min_delay=1, max_delay=self.mqtt_config.reconnect_delay)
        self._client.connect_async(
            self.mqtt_config.broker,
            self.mqtt_config.port,
            self.mqtt_config.keepalive,
        )
        self._client.loop_start()
        self.logger.info(f"MQTTReceiver started, connecting to {self.mqtt_config.broker}")

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()
        self.logger.info("MQTTReceiver stopped")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.info(f"MQTT connected to {self.mqtt_config.broker}:{self.mqtt_config.port}")
            for tm in self.mqtt_config.topics:
                client.subscribe(tm.topic, qos=1)
                self.logger.info(f"Subscribed: {tm.topic} → {tm.table}")
        else:
            self.logger.warning(f"MQTT connect failed, rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning(f"MQTT disconnected unexpectedly (rc={rc}), auto-reconnecting...")

    def _on_message(self, client, userdata, msg):
        try:
            table = self._topic_table_map.get(msg.topic)
            if not table:
                self.logger.warning(f"Unknown topic: {msg.topic}")
                return

            if not msg.payload:
                self.logger.warning(f"Empty payload on topic: {msg.topic}, skipped")
                return

            payload = json.loads(msg.payload.decode("utf-8"))

            # Always save raw JSON locally (before any averaging)
            self.raw_json_writer.write(table, payload)

            # Hand off to aggregator (pass-through or downsampling)
            self.aggregator.ingest(table, payload)

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e} | raw: {msg.payload}")
        except Exception as e:
            self.logger.error(f"on_message error: {e}")
