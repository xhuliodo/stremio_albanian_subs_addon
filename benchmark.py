from pathlib import Path
import os
import re
import subprocess
import time
import srt

# LIMITING THREADS TO SIMULATE RASPBERRY PI 5 PERFORMANCE
# CRITICAL: Set these BEFORE importing torch or transformers
# os.environ["OMP_NUM_THREADS"] = "4"
# os.environ["OPENBLAS_NUM_THREADS"] = "4"
# os.environ["MKL_NUM_THREADS"] = "4"

import ctranslate2
from transformers import AutoTokenizer

print("Loading AI Model...")
model_name = "Helsinki-NLP/opus-mt-en-sq"
tokenizer = AutoTokenizer.from_pretrained(model_name)
translator = ctranslate2.Translator("opus-mt-en-sq-ct2", compute_type="int8")


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
            print("  Warning: Could not read temperature")
            break
        if temp < max_temp:
            print(f"  Temperature OK: {temp}°C\n")
            break
        print(f"  Temperature too high: {temp}°C. Sleeping 30 seconds...")
        time.sleep(check_interval)


# Configuration
benchmark_folder = "./benchmark"
translated_folder = Path(benchmark_folder) / "translated"
translated_folder.mkdir(exist_ok=True)

# REDUCED BATCH SIZE for Raspberry Pi
batch_size = 4
temp_threshold = 75

# Get all .srt files
srt_files = sorted(Path(benchmark_folder).glob("*.srt"))

if not srt_files:
    print(f"No .srt files found in {benchmark_folder}")
    exit()

print(f"Found {len(srt_files)} subtitle files\n")

total_lines = 0
total_time = 0

for srt_file in srt_files:
    # Parse filename: {tv/mov}_{id}.srt
    match = re.match(r"(tv|mov)_(\d+)\.srt", srt_file.name)
    if not match:
        print(f"Skipping {srt_file.name} - invalid naming pattern")
        continue

    file_type = match.group(1)
    file_id = match.group(2)

    with open(srt_file, "r", encoding="utf-8") as f:
        subtitles = list(srt.parse(f.read()))

    subtitle_texts = [sub.content for sub in subtitles]
    print(f"{file_type}_{file_id}: {len(subtitle_texts)} lines")

    start_time = time.time()

    # Translate in batches
    translated_texts = []
    for i in range(0, len(subtitle_texts), batch_size):
        batch = subtitle_texts[i : i + batch_size]

        # 1. Tokenize text into words/subwords
        source = [
            tokenizer.convert_ids_to_tokens(tokenizer.encode(text)) for text in batch
        ]

        # 2. Translate using the ultra-fast C++ engine
        results = translator.translate_batch(source)

        # 3. Decode back into readable strings
        for result in results:
            target_ids = tokenizer.convert_tokens_to_ids(result.hypotheses[0])
            translated_texts.append(
                tokenizer.decode(target_ids, skip_special_tokens=True)
            )

    elapsed = time.time() - start_time
    total_lines += len(subtitle_texts)
    total_time += elapsed

    for sub, translation in zip(subtitles, translated_texts):
        sub.content = translation

    output_file = translated_folder / f"{file_type}_{file_id}_helsinki.srt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))

    print(
        f"  Translated in {elapsed:.2f}s "
        f"({len(subtitle_texts)/elapsed:.1f} lines/s)\n"
    )

    # Check temperature and cool down if needed
    temp = get_cpu_temp()
    if temp:
        print(f"  Temperature: {temp}°C")
        if temp >= temp_threshold:
            wait_for_cooldown(temp_threshold)


print(f"Total: {total_lines} lines in {total_time:.2f}s")
print(f"Average lines: {total_lines/30}")
print(f"Average: {total_lines/total_time:.1f} lines/s")
print("Benchmark completed!")
