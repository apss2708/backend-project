import logging
import sys
from app.core.config import settings

def setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(filename)s:%(lineno)d - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )
    logger = logging.getLogger("app")
    logger.info(f"Logging initialized with level: {settings.LOG_LEVEL}")
