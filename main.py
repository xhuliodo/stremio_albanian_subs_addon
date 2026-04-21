from config import (
    CACHE_DIR,
    setup_logger,
    BATCH_SIZE,
    AVG_LINE_PER_S,
    setup_sub_client,
)

setup_logger()

from loguru import logger
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from urllib.parse import parse_qs
from fastapi.staticfiles import StaticFiles

from translation import translate_background_task, translation_executor
from utils import (
    change_extension_to_srt,
    generate_temporary_subtitle,
    write_subs_to_cache,
)
from prometheus_client import make_asgi_app

import metrics  # ensures all metrics are registered on startup

subtitles_client = setup_sub_client()

app = FastAPI()

metrics_endpoint = make_asgi_app()
app.mount("/metrics", metrics_endpoint)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global error: {exc}")
    metrics.thuaji_xhulios.inc()
    return JSONResponse(status_code=500, content={"error": "Problem, thuaji xhulios"})


@app.get("/manifest.json")
def manifest():
    return JSONResponse(
        status_code=200,
        content={
            "id": "albaniansubtitles",
            "version": "0.0.1",
            "name": "albaniansubtitles",
            "description": "Translates english subtitles to albanian.",
            "resources": ["subtitles"],
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "catalogs": [],
        },
    )


app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")


@app.get("/subtitles/{type}/{id}/{extra}.json")
def get_subtitles(type: str, id: str, extra: str, request: Request):
    # Get the base URL (e.g., http://localhost:8000)
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    # Parse the incoming request to extract IMDb ID, season, episode, and filename
    try:
        parts = id.split(":")
        imdb_id = parts[0]
        season = int(parts[1]) if len(parts) > 1 else None
        episode = int(parts[2]) if len(parts) > 2 else None
        parsed = parse_qs(extra)
        filename = parsed.get("filename", [""])[0]
        # video_hash = parsed.get("videoHash", "")[0]
    except (ValueError, IndexError) as e:
        logger.warning(f"Malformed request path — id={id}, extra={extra}: {e}")
        return JSONResponse(
            status_code=400, content={"error": "Problem, thuaji xhulios"}
        )
    logger.info(
        f"Received request for IMDb ID: {imdb_id}, Season: {season}, Episode: {episode}, Filename: {filename}"
    )

    # Remove .codec extension from filename and replace with .srt
    filename = change_extension_to_srt(filename)

    # Check if the translated subtitle already exists in the cache
    if os.path.exists(f"{CACHE_DIR}/{filename}"):
        return JSONResponse(
            status_code=200,
            content={
                "subtitles": [
                    {
                        "id": filename,
                        "url": f"{base_url}/{CACHE_DIR}/{filename}",
                        "lang": "sq",
                        "label": "Shqip",
                    }
                ]
            },
        )

    # If not in cache, download and parse the english subtitles
    with metrics.sub_cli_fetch_time.time():
        subtitles = subtitles_client.download_and_parse(
            imdb_id=imdb_id,
            original_filename=filename,
            season=season,
            episode=episode,
        )

    # If subtitles are not found, return a JSON response with a "not found" subtitle pointing to a placeholder file
    if subtitles is None:
        return JSONResponse(
            status_code=200,
            content={
                "subtitles": [
                    {
                        "id": f"{filename}",
                        "url": f"{base_url}/{CACHE_DIR}/not_found.srt",
                        "lang": "sq",
                        "label": "Shqip",
                    }
                ]
            },
        )

    try:
        # Start the translation in a background thread to avoid blocking the main server thread
        translation_executor.submit(
            translate_background_task, CACHE_DIR, filename, subtitles, BATCH_SIZE
        )
        # Generate a temporary subtitle file with a countdown message while the translation is being processed in the background
        sub_length = len(subtitles)
        temp_sub = generate_temporary_subtitle(sub_length, AVG_LINE_PER_S)
        write_subs_to_cache(CACHE_DIR, filename, temp_sub)
        write_subs_to_cache(CACHE_DIR, f"original_{filename}", subtitles)
    except Exception as e:
        logger.error(f"Failed to queue translation or write temp file: {e}")
        return JSONResponse(
            status_code=500, content={"error": "Problem, thuaji xhulios"}
        )
    return JSONResponse(
        status_code=200,
        content={
            "subtitles": [
                {
                    "id": f"{filename}",
                    "url": f"{base_url}/{CACHE_DIR}/{filename}",
                    "lang": "sq",
                    "label": "Shqip",
                }
            ]
        },
    )
