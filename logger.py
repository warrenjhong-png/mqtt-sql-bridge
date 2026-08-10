import logging
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logger(log_dir: str = "logs", level: str = "INFO") -> logging.Logger:
    """建立同時輸出至 console 與每日輪替檔案的共用 logger。"""
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("mqtt_sql_bridge")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "bridge.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
