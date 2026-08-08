import logging
from logging.handlers import RotatingFileHandler
import os

class AppLogger:
    def __init__(self):
        self.logger = logging.getLogger("AutoConnectRust")
        self.logger.setLevel(logging.DEBUG)
        
        # Prevent adding handlers multiple times if instantiated again
        if not self.logger.handlers:
            log_format = logging.Formatter(
                '%(asctime)s [%(levelname)s] %(module)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # File Handler (5MB max size, keep 2 backups)
            log_dir = os.path.join(os.getenv('APPDATA', os.getcwd()), 'RustAutoConnect')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, 'app.log')
            file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(log_format)
            
            self.logger.addHandler(file_handler)

    def info(self, msg: str):
        self.logger.info(msg)
        
    def error(self, msg: str):
        self.logger.error(msg)
        
    def debug(self, msg: str):
        self.logger.debug(msg)
        
    def warning(self, msg: str):
        self.logger.warning(msg)

app_logger = AppLogger()
