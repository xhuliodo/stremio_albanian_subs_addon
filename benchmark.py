from logger import setup_logger

setup_logger()
from loguru import logger
from pathlib import Path
import re
import subprocess
import time
import srt
from translation import translate_background_task


# Configuration
BENCHMARK_FOLDER = "./benchmark"
translated_folder = Path(BENCHMARK_FOLDER) / "translated"
translated_folder.mkdir(exist_ok=True)

BATCH_SIZE = 512
TEMP_THRESHOLD = 78


def get_cpu_temp():
    """Get CPU temperature on Raspberry Pi"""
    try:
        temp_str = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        temp = float(temp_str.split("=")[1].split("'")[0])
        return temp
    except:
        return None


def wait_for_cooldown(max_temp=75, check_interval=30):
    """Sleep until temp drops below max_temp"""
    while True:
        temp = get_cpu_temp()
        if temp is None:
            logger.warning("Could not read temperature")
            break
        if temp < max_temp:
            logger.info(f"Temperature OK: {temp}°C")
            break
        logger.warning(f"Temperature too high: {temp}°C. Sleeping 30 seconds...")
        time.sleep(check_interval)


# Get all .srt files
srt_files = sorted(Path(BENCHMARK_FOLDER).glob("*.srt"))

if not srt_files:
    logger.error(f"No .srt files found in {BENCHMARK_FOLDER}")
    exit()

logger.info(f"Found {len(srt_files)} subtitle files\n")

total_lines = 0
total_time = 0

for srt_file in srt_files:
    # Parse filename: {tv/mov}_{id}.srt
    match = re.match(r"(tv|mov)_(\d+)\.srt", srt_file.name)
    if not match:
        logger.warning(f"Skipping {srt_file.name} - invalid naming pattern")
        continue

    with open(srt_file, "r", encoding="utf-8") as f:
        subtitles = list(srt.parse(f.read()))

    start_time = time.time()

    translate_background_task(
        cache_dir=str(translated_folder),
        filename=srt_file.name,
        subtitles=subtitles,
        batch_size=BATCH_SIZE,
    )

    elapsed = time.time() - start_time
    total_lines += len(subtitles)
    total_time += elapsed

    logger.info(
        f"Translated in {elapsed:.2f}s " f"({len(subtitles)/elapsed:.1f} lines/s)\n"
    )

    # Check temperature and cool down if needed
    temp = get_cpu_temp()
    if temp:
        logger.info(f"Temperature: {temp}°C")
        if temp >= TEMP_THRESHOLD:
            wait_for_cooldown(TEMP_THRESHOLD)


logger.info(f"Total: {total_lines} lines in {total_time:.2f}s")
logger.info(f"Average lines: {total_lines/30}")
logger.info(f"Average: {total_lines/total_time:.1f} lines/s")
logger.info("Benchmark completed!")
