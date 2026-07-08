from dataclasses import dataclass, field
from typing import Dict, List

import yaml


@dataclass
class TopicContext:
    factory_code: str
    system_type: str
    equipment_type: str
    machine_id: str


@dataclass
class TopicTableMapping:
    topic: str
    table: str
    context: TopicContext


@dataclass
class MQTTConfig:
    broker: str
    port: int
    username: str
    password: str
    client_id: str
    keepalive: int
    reconnect_delay: int
    topics: List[TopicTableMapping]


@dataclass
class DBConfig:
    server: str
    database: str
    username: str
    password: str
    driver: str
    reconnect_delay: int


@dataclass
class LogConfig:
    dir: str
    level: str


@dataclass
class RawJsonConfig:
    dir: str


@dataclass
class AppConfig:
    mqtt: MQTTConfig
    db: DBConfig
    log: LogConfig
    raw_json: RawJsonConfig
    queue_maxsize: int
    sampling_interval_seconds: int  # 0 = pass-through, N > 0 = average over N seconds


class ConfigLoader:
    def __init__(
        self,
        config_path: str = "config.yaml",
        mapping_path: str = "field_mapping.yaml",
    ):
        self.config_path = config_path
        self.mapping_path = mapping_path

    def load(self) -> tuple[AppConfig, Dict[str, str]]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        with open(self.mapping_path, "r", encoding="utf-8") as f:
            field_mapping: Dict[str, str] = yaml.safe_load(f)

        mqtt_raw = raw["mqtt"]
        mqtt = MQTTConfig(
            broker=mqtt_raw["broker"],
            port=mqtt_raw.get("port", 1883),
            username=mqtt_raw.get("username", ""),
            password=mqtt_raw.get("password", ""),
            client_id=mqtt_raw.get("client_id", "mqtt_sql_bridge"),
            keepalive=mqtt_raw.get("keepalive", 60),
            reconnect_delay=mqtt_raw.get("reconnect_delay", 10),
            topics=[
                TopicTableMapping(
                    topic=t["topic"],
                    table=t["table"],
                    context=TopicContext(
                        factory_code=t.get("context", {}).get("factory_code", ""),
                        system_type=t.get("context", {}).get("system_type", ""),
                        equipment_type=t.get("context", {}).get("equipment_type", ""),
                        machine_id=t.get("context", {}).get("machine_id", ""),
                    ),
                )
                for t in mqtt_raw["topics"]
            ],
        )

        db_raw = raw["db"]
        db = DBConfig(
            server=db_raw["server"],
            database=db_raw["database"],
            username=db_raw["username"],
            password=db_raw["password"],
            driver=db_raw.get("driver", "ODBC Driver 17 for SQL Server"),
            reconnect_delay=db_raw.get("reconnect_delay", 5),
        )

        log_raw = raw.get("log", {})
        log = LogConfig(
            dir=log_raw.get("dir", "logs"),
            level=log_raw.get("level", "INFO"),
        )

        rj_raw = raw.get("raw_json", {})
        raw_json = RawJsonConfig(dir=rj_raw.get("dir", "raw_json"))

        config = AppConfig(
            mqtt=mqtt,
            db=db,
            log=log,
            raw_json=raw_json,
            queue_maxsize=raw.get("queue_maxsize", 10000),
            sampling_interval_seconds=raw.get("sampling_interval_seconds", 0),
        )

        return config, field_mapping
