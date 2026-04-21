from datetime import timedelta
import textwrap
import srt
import ctranslate2
from transformers import AutoTokenizer
import concurrent.futures
import metrics
from utils import delete_subs_from_cache, strip_html_tags, write_subs_to_cache
from loguru import logger

logger.info("Loading AI Model...")
model_name = "Helsinki-NLP/opus-mt-en-sq"
tokenizer = AutoTokenizer.from_pretrained(model_name, force_download=False)
translator = ctranslate2.Translator("opus-mt-en-sq-ct2", compute_type="int8")

# Create a ThreadPoolExecutor with exactly ONE worker.
# This ensures that no matter how many translation requests come in,
# only 1 will run at a time. The rest will wait in a queue.
translation_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

CHARS_PER_SECOND = 17
GAP_BUFFER = timedelta(milliseconds=100)
WRAP_WIDTH = 42


def reassemble_subtitles(
    subtitles: list[srt.Subtitle], translated_texts: list[str]
) -> None:
    for i, (sub, translation) in enumerate(zip(subtitles, translated_texts)):
        current_duration = (sub.end - sub.start).total_seconds()
        required_duration = len(translation) / CHARS_PER_SECOND

        if required_duration > current_duration:
            new_end = sub.start + timedelta(seconds=required_duration)

            if i + 1 < len(subtitles):
                max_end = subtitles[i + 1].start - GAP_BUFFER
                sub.end = min(new_end, max_end)
            else:
                sub.end = new_end

        sub.content = textwrap.fill(translation, width=WRAP_WIDTH)


def translate_background_task(
    cache_dir: str, filename: str, subtitles: list[srt.Subtitle], batch_size: int
):
    logger.info(f"[{filename}] Starting subtitle translation...")
    try:
        with metrics.translation_time.time():
            # Extract all subtitle text into a list
            texts = [strip_html_tags(sub.content) for sub in subtitles]

            # Translate in batches
            translated_texts = []

            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]

                # 1. Tokenize text into words/subwords
                source = [
                    tokenizer.convert_ids_to_tokens(tokenizer.encode(text))
                    for text in batch
                ]

                # 2. Translate using the ultra-fast C++ engine
                results = translator.translate_batch(
                    source,
                    length_penalty=0.6,
                )

                # 3. Decode back into readable strings
                for result in results:
                    target_ids = tokenizer.convert_tokens_to_ids(result.hypotheses[0])
                    translated_texts.append(
                        tokenizer.decode(target_ids, skip_special_tokens=True)
                    )
            # Reassemble translated subtitles
            reassemble_subtitles(subtitles, translated_texts)
            # Save to disk
            write_subs_to_cache(cache_dir, filename, subtitles)

            logger.info(f"[{filename}] Translation complete. Saved to cache.")

    except Exception as e:
        logger.error(f"[{filename}] Translation failed: {e}")
        delete_subs_from_cache(cache_dir, filename)
