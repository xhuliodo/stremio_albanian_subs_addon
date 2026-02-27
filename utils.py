import datetime
import srt
from pathlib import Path


def change_extension_to_srt(filename: str) -> str:
    return str(Path(filename).with_suffix(".srt"))


def write_subs_to_cache(cache_dir: str, filename: str, subtitles: list[srt.Subtitle]):
    output_path = f"{cache_dir}/{filename}"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))


def estimate_translation_time_str(seconds: int):
    minutes, secs = divmod(int(seconds), 60)
    hours, mins = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {mins}m {secs}s"
    elif minutes > 0:
        return f"{mins}m {secs}s"
    else:
        return f"{secs}s"


def estimate_translation_time_sec(num_lines, avg_line_per_s) -> int:
    seconds = num_lines / avg_line_per_s
    return int(seconds)


def generate_temporary_subtitle(
    sub_len: int, avg_line_per_s: float
) -> list[srt.Subtitle]:
    # 1. Calculate estimated time in SECONDS
    estimated_seconds = estimate_translation_time_sec(sub_len, avg_line_per_s)
    estimated_seconds += 10  # Add a buffer for overhead and variability

    countdown_subs = []
    interval = 5  # Update the text on screen every 5 seconds

    # 2. Generate the countdown sequence
    for elapsed in range(0, estimated_seconds, interval):
        remaining = estimated_seconds - elapsed
        block_end = min(elapsed + interval, estimated_seconds)
        time_str = estimate_translation_time_str(remaining)

        countdown_subs.append(
            srt.Subtitle(
                index=len(countdown_subs) + 1,
                start=datetime.timedelta(seconds=elapsed),
                end=datetime.timedelta(seconds=block_end),
                content=("⚠️ Titrat po perkthehen...\n" f"Prit rreth {time_str}."),
            )
        )

    # 3. Add the final completion message
    countdown_subs.append(
        srt.Subtitle(
            index=len(countdown_subs) + 1,
            start=datetime.timedelta(seconds=estimated_seconds),
            end=datetime.timedelta(hours=10),  # Keep on screen for 10 hours
            content=(
                "✅ Perkthimi duhet te kete mbaruar!\n"
                "Te lutem zgjidh titrat prap per ti pare."
            ),
        )
    )

    return countdown_subs
