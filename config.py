import sys
from dotenv import load_dotenv
from loguru import logger
import os

from subtitle_manager import SubtitleManager

load_dotenv()

BATCH_SIZE = 512
_batch_size = os.getenv("BATCH_SIZE")
if _batch_size:
    BATCH_SIZE = int(_batch_size)

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

AVG_LINE_PER_S = 142  # tested on macbook
_avg_line_per_s = os.getenv("AVG_LINE_PER_S")
if _avg_line_per_s:
    AVG_LINE_PER_S = float(_avg_line_per_s)


LOG_DIR = "logs"


SUB_SOURCE_API_KEY = os.getenv("SUBSOURCE_API_KEY")
if not SUB_SOURCE_API_KEY:
    logger.error("SUBSOURCE_API_KEY is not set in the environment variables.")
    exit(1)

SUB_DL_API_KEY = os.getenv("SUB_DL_API_KEY")
if not SUB_DL_API_KEY:
    logger.error("SUB_DL_API_KEY is not set in the environment variables.")
    exit(1)

USER_AGENT = os.getenv("USER_AGENT", "albaniansubtitles")


def setup_logger():
    os.makedirs(LOG_DIR, exist_ok=True)
    logger.remove()
    logger.add(
        f"{LOG_DIR}/app.log",
        rotation="100 MB",
        retention="90 days",
        level="INFO",
    )
    logger.add(sys.stderr, level="INFO")
    logger.info("Logger initialized and writing to logs/app.log")


def setup_sub_client():
    sub_source_api_key = os.getenv("SUBSOURCE_API_KEY")
    if not sub_source_api_key:
        logger.error("SUBSOURCE_API_KEY is not set in the environment variables.")
        exit(1)

    sub_dl_api_key = os.getenv("SUB_DL_API_KEY")
    if not sub_dl_api_key:
        logger.error("SUB_DL_API_KEY is not set in the environment variables.")
        exit(1)
    user_agent = os.getenv("USER_AGENT", "albaniansubtitles")

    subtitles_client = SubtitleManager(sub_source_api_key, sub_dl_api_key, user_agent)

    return subtitles_client
