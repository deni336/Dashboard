import logging
import os
from datetime import datetime
from config_manager import ConfigManager

class GlobalLogger:
    config = ConfigManager()

    @classmethod
    def get_logger(cls, name):
        log_dir = cls.config.get('Logging', 'path')
        log_level = cls.config.get('Logging', 'loglevel')

        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, log_level.upper()))

        # Create a log directory if it doesn't exist
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Create a log file with the current date
        current_date = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(log_dir, f"{current_date}.log")

        # Create a file handler with the new log file
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))

        # Remove previous handlers if they exist to avoid duplicate logs
        if logger.hasHandlers():
            logger.handlers.clear()

        logger.addHandler(handler)
        logger.addHandler(console_handler)

        return logger
