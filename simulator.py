"""
MQTT 空壓機資料模擬器

從 config.yaml 讀取 broker 設定，對所有設定的 topic 模擬發送空壓機感測資料。
每個 topic（機台）的基準值略有不同，以模擬多台機器的差異。
發送頻率：每秒 1 次（與實際感測器相同）。

用法：
    python simulator.py
    python simulator.py --interval 2    # 每 2 秒發一次
    python simulator.py --topic zhongli/zone1/compressor/c1/telemetry  # 只模擬單一 topic
"""

import argparse
import json
import random
import signal
import sys
import time
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt
import yaml

TZ_TAIPEI = timezone(timedelta(hours=8))


# ------------------------------------------------------------------
# 每台機器的基準值（模擬三台機器略有差異）
# ------------------------------------------------------------------
MACHINE_PROFILES = [
    {
        "drive_type": "VSD",
        "flow_base": 120.0,
        "pressure_base": 0.72,
        "freq_base": 45.0,
        "power_base": 18.1,
        "current_base": 32.4,
        "energy_start": 14520.0,
    },
    {
        "drive_type": "VSD",
        "flow_base": 115.0,
        "pressure_base": 0.70,
        "freq_base": 43.0,
        "power_base": 17.5,
        "current_base": 31.0,
        "energy_start": 12000.0,
    },
    {
        "drive_type": "NON-VSD",
        "flow_base": 110.0,
        "pressure_base": 0.68,
        "freq_base": 50.0,   # 定頻機固定 50Hz
        "power_base": 16.8,
        "current_base": 30.0,
        "energy_start": 9800.0,
    },
]


def jitter(value: float, pct: float = 0.02) -> float:
    """在 value ± pct% 範圍內加入隨機雜訊。"""
    return round(value * (1 + random.uniform(-pct, pct)), 3)


def make_payload(profile: dict, energy_counter: float) -> dict:
    """根據 profile 產生一筆模擬資料。"""
    flow = jitter(profile["flow_base"], 0.03)
    pressure = jitter(profile["pressure_base"], 0.02)
    freq = profile["freq_base"] if profile["drive_type"] == "NON-VSD" else jitter(profile["freq_base"], 0.05)
    power = jitter(profile["power_base"], 0.03)

    return {
        "compressor_drive_type": profile["drive_type"],
        "timestamp": datetime.now(TZ_TAIPEI).isoformat(),
        "area_entrance_instant_flow":       round(flow * 1.05, 3),
        "area_entrance_gas_pressure":       round(pressure - 0.07, 3),
        "compressor_outlet_instant_flow":   round(flow, 3),
        "compressor_outlet_pressure":       round(pressure, 3),
        "air_tank_pressure":                round(pressure - 0.04, 3),
        "compressor_unload_pressure":       round(jitter(6.5, 0.01), 2),
        "compressor_load_pressure":         round(jitter(5.9, 0.01), 2),
        "compressor_vsd_target_pressure":   round(jitter(6.0, 0.01), 2),
        "vfd_motor_frequency":              round(freq, 2),
        "compressor_inlet_temp":            round(jitter(28.5, 0.03), 2),
        "compressor_outlet_temp":           round(jitter(75.3, 0.03), 2),
        "compressor_operating_temp":        round(jitter(68.1, 0.02), 2),
        "compressor_energy_consumption":    round(energy_counter, 3),
        "compressor_power":                 round(power, 2),
        "compressor_input_current":         round(jitter(profile["current_base"], 0.03), 2),
        "compressor_input_voltage":         round(jitter(380.0, 0.005), 1),
    }


class Simulator:
    def __init__(self, broker: str, port: int, topics: list[str], interval: float):
        self.broker = broker
        self.port = port
        self.topics = topics
        self.interval = interval

        # 每個 topic 對應一個 profile（循環使用），並維護累積電能計數器
        self._profiles = []
        self._energy_counters = []
        for i, _ in enumerate(topics):
            profile = MACHINE_PROFILES[i % len(MACHINE_PROFILES)]
            self._profiles.append(profile)
            self._energy_counters.append(profile["energy_start"])

        self._client = mqtt.Client(client_id="mqtt_simulator")
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._running = False

    def start(self):
        print(f"Connecting to broker {self.broker}:{self.port} ...")
        self._client.connect(self.broker, self.port, keepalive=60)
        self._client.loop_start()
        self._running = True
        self._loop()

    def stop(self):
        self._running = False
        self._client.loop_stop()
        self._client.disconnect()
        print("\nSimulator stopped.")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected. Publishing to {len(self.topics)} topic(s) every {self.interval}s:")
            for t in self.topics:
                print(f"  {t}")
        else:
            print(f"Connection failed, rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print(f"Disconnected unexpectedly (rc={rc})")

    def _loop(self):
        while self._running:
            for i, topic in enumerate(self.topics):
                # 累積電能：每秒增加 power(kW) / 3600 kWh
                power = self._profiles[i]["power_base"]
                self._energy_counters[i] += power / 3600

                payload = make_payload(self._profiles[i], self._energy_counters[i])
                msg = json.dumps(payload, ensure_ascii=False)
                result = self._client.publish(topic, msg, qos=1)

                status = "OK" if result.rc == 0 else f"FAILED(rc={result.rc})"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {topic.split('/')[-2]} → {status}  "
                      f"flow={payload['compressor_outlet_instant_flow']}  "
                      f"pressure={payload['compressor_outlet_pressure']}  "
                      f"power={payload['compressor_power']}kW")

            time.sleep(self.interval)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="空壓機 MQTT 資料模擬器")
    parser.add_argument("--config", default="config.yaml", help="config 路徑（預設：config.yaml）")
    parser.add_argument("--interval", type=float, default=1.0, help="發送間隔秒數（預設：1.0）")
    parser.add_argument("--topic", type=str, default=None, help="只模擬單一 topic（不指定則模擬 config 內全部）")
    args = parser.parse_args()

    cfg = load_config(args.config)
    broker = cfg["mqtt"]["broker"]
    port = cfg["mqtt"].get("port", 1883)

    if args.topic:
        topics = [args.topic]
    else:
        topics = [t["topic"] for t in cfg["mqtt"]["topics"]]

    sim = Simulator(broker, port, topics, args.interval)

    def handle_signal(sig, frame):
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    sim.start()


if __name__ == "__main__":
    main()
