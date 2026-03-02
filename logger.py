from loguru import logger

LOG_DIR = "logs"


def setup_logger():
    logger.add(
        f"{LOG_DIR}/app.log",
        rotation="100 MB",
        retention="30 days",
        level="INFO",
    )
    logger.info("Logger initialized and writing to logs/app.log")
