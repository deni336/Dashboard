import getpass
from global_logger import GlobalLogger
from config_handler import ConfigHandler

logger = GlobalLogger.get_logger("DBUtils")
config = ConfigHandler()

def get_default_db_path():
    """Generate the default DB path based on current user."""
    user = getpass.getuser()
    config.get("Database", "chatdbpath")
    return fr"C:/Users/{user}/Kasugai/ChatHistory.db"
