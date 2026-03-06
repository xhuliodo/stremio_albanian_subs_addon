import textwrap

import srt
import ctranslate2
from transformers import AutoTokenizer
import concurrent.futures
from utils import write_subs_to_cache
from loguru import logger

logger.info("Loading AI Model...")
model_name = "Helsinki-NLP/opus-mt-en-sq"
tokenizer = AutoTokenizer.from_pretrained(model_name, force_download=False)
translator = ctranslate2.Translator("opus-mt-en-sq-ct2", compute_type="int8")

# Create a ThreadPoolExecutor with exactly ONE worker.
# This ensures that no matter how many translation requests come in,
# only 1 will run at a time. The rest will wait in a queue.
translation_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def translate_background_task(
    cache_dir: str, filename: str, subtitles: list[srt.Subtitle], batch_size: int
):
    logger.info(f"[{filename}] Starting subtitle translation...")

    # Extract all subtitle text into a list
    texts = [sub.content for sub in subtitles]

    # Translate in batches
    translated_texts = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        # 1. Tokenize text into words/subwords
        source = [
            tokenizer.convert_ids_to_tokens(tokenizer.encode(text)) for text in batch
        ]

        # 2. Translate using the ultra-fast C++ engine
        results = translator.translate_batch(
            source,
            length_penalty=0.8,
            # max_input_length=batch_size,
            # max_decoding_length=batch_size,
        )

        # 3. Decode back into readable strings
        for result in results:
            target_ids = tokenizer.convert_tokens_to_ids(result.hypotheses[0])
            translated_texts.append(
                tokenizer.decode(target_ids, skip_special_tokens=True)
            )
    # Reassemble translated subtitles
    for sub, translation in zip(subtitles, translated_texts):
        wrapped_text = textwrap.fill(translation, width=42)
        sub.content = wrapped_text

    # Save to disk
    write_subs_to_cache(cache_dir, filename, subtitles)

    logger.info(f"[{filename}] Translation complete. Saved to cache.")
