from prometheus_client import Counter, Histogram

sub_cli_fetch_time = Histogram(
    "sub_cli_fetch_duration_seconds",
    "Time spent fetching subtitles via CLI",
)

translation_time = Histogram(
    "translation_duration_seconds",
    "Time spent translating subtitles",
)
