from logger import setup_logger

setup_logger()

from loguru import logger
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from urllib.parse import parse_qs
from fastapi.staticfiles import StaticFiles

from subtitle_manager import SubtitleManager
from translation import translate_background_task, translation_executor
from utils import (
    change_extension_to_srt,
    generate_temporary_subtitle,
    write_subs_to_cache,
)
from dotenv import load_dotenv


PORT = 8000
BATCH_SIZE = 128
CACHE_DIR = "cache"
AVG_LINE_PER_S = 142.7  # tested on macbook


load_dotenv()


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

os.makedirs(CACHE_DIR, exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global error: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/manifest.json")
def manifest():
    return JSONResponse(
        {
            "id": "albaniansubtitles",
            "version": "0.0.1",
            "name": "albaniansubtitles",
            "description": "Translates english subtitles to albanian.",
            "resources": ["subtitles"],
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "catalogs": [],
        }
    )


app.mount(f"/{CACHE_DIR}", StaticFiles(directory=CACHE_DIR), name="cache")


@app.get("/subtitles/{type}/{id}/{extra}.json")
def get_subtitles(type: str, id: str, extra: str, request: Request):
    # Get the base URL (e.g., http://192.168.1.50:8000)
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    # Parse the incoming request to extract IMDb ID, season, episode, and filename
    parts = id.split(":")
    imdb_id = parts[0]
    season = int(parts[1]) if len(parts) > 1 else None
    episode = int(parts[2]) if len(parts) > 2 else None
    parsed = parse_qs(extra)
    # video_hash = parsed.get("videoHash", "")[0]
    filename = parsed.get("filename", "")[0]
    logger.info(
        f"Received request for IMDb ID: {imdb_id}, Season: {season}, Episode: {episode}, Filename: {filename}"
    )

    # Remove .codec extension from filename and replace with .srt
    filename = change_extension_to_srt(filename)

    # Check if the translated subtitle already exists in the cache
    if os.path.exists(f"{CACHE_DIR}/{filename}"):
        return JSONResponse(
            {
                "subtitles": [
                    {
                        "id": filename,
                        "url": f"http://0.0.0.0:{PORT}/cache/{filename}",
                        "lang": "sq",
                        "label": "Shqip",
                    }
                ]
            }
        )

    # If not in cache, download and parse the english subtitles
    subtitles = subtitles_client.download_and_parse(
        imdb_id=imdb_id,
        original_filename=filename,
        season=season,
        episode=episode,
    )

    # If subtitles are not found, return a JSON response with a "not found" subtitle pointing to a placeholder file
    if subtitles is None:
        return JSONResponse(
            {
                "subtitles": [
                    {
                        "id": f"{filename}",
                        "url": f"http://0.0.0.0:{PORT}/cache/not_found.srt",
                        "lang": "sq",
                        "label": "Shqip",
                    }
                ]
            }
        )

    # Start the translation in a background thread to avoid blocking the main server thread
    translation_executor.submit(
        translate_background_task, CACHE_DIR, filename, subtitles, BATCH_SIZE
    )

    # Generate a temporary subtitle file with a countdown message while the translation is being processed in the background
    sub_length = len(subtitles)
    temp_sub = generate_temporary_subtitle(sub_length, AVG_LINE_PER_S)
    write_subs_to_cache(CACHE_DIR, filename, temp_sub)
    write_subs_to_cache(CACHE_DIR, f"original_{filename}", subtitles)

    return JSONResponse(
        {
            "subtitles": [
                {
                    "id": f"{filename}",
                    "url": f"http://0.0.0.0:{PORT}/cache/{filename}",
                    "lang": "sq",
                    "label": "Shqip",
                }
            ]
        }
    )
