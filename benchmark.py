from pathlib import Path
import os
import re
import time
import srt
from transformers import MarianMTModel, MarianTokenizer

# LIMITING THREADS TO SIMULATE RASPBERRY PI 5 PERFORMANCE
# os.environ["OMP_NUM_THREADS"] = "4"
# os.environ["OPENBLAS_NUM_THREADS"] = "4"
# os.environ["MKL_NUM_THREADS"] = "4"

import torch
torch.set_num_threads(4)
device = torch.device("cpu")

print("Loading AI Model...")
model_name = "Helsinki-NLP/opus-mt-en-sq"
tokenizer = MarianTokenizer.from_pretrained(model_name)
model = MarianMTModel.from_pretrained(model_name)

# Configuration
benchmark_folder = "./benchmark"
translated_folder = Path(benchmark_folder) / "translated"
translated_folder.mkdir(exist_ok=True)
batch_size = 32

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
    
    # Read and parse subtitle file
    with open(srt_file, "r", encoding="utf-8") as f:
        subtitles = list(srt.parse(f.read()))
    
    subtitle_texts = [sub.content for sub in subtitles]
    
    print(f"{file_type}_{file_id}: {len(subtitle_texts)} lines")
    
    start_time = time.time()
    
    # Translate in batches
    translated_texts = []
    for i in range(0, len(subtitle_texts), batch_size):
        batch = subtitle_texts[i:i + batch_size]
        inputs = tokenizer(batch, return_tensors="pt", padding=True)
        outputs = model.generate(**inputs)
        translations = tokenizer.batch_decode(
          outputs,
          skip_special_tokens=True
        )
        translated_texts.extend(translations)
    
    elapsed = time.time() - start_time
    total_lines += len(subtitle_texts)
    total_time += elapsed
    
    # Update subtitles with translations
    for sub, translation in zip(subtitles, translated_texts):
        sub.content = translation
    
    # Save translated file
    output_file = srt_file.parent / f"translated/{file_type}_{file_id}_helsinki.srt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))
    
    print(
      f"  Translated in {elapsed:.2f}s "
      f"({len(subtitle_texts)/elapsed:.1f} lines/s)\n"
    )


print(f"Total: {total_lines} lines in {total_time:.2f}s")
print(f"Average lines: {total_lines/30}")
print(f"Average: {total_lines/total_time:.1f} lines/s")
print("Benchmark completed!")