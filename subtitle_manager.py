import difflib
import io
import zipfile

import babelfish
from loguru import logger
from guessit import guessit
import srt
from pathlib import Path

import time
import requests
from typing import Any, Dict, List, Optional, cast
import json


class SubtitleManager:
    """
    A unified manager that orchestrates SubSource and SubDl providers.
    It attempts to find subtitles from providers sequentially.
    """

    def __init__(
        self,
        subsource_api_key: str,
        subdl_api_key: str,
        user_agent: str,
        timeout: int = 20,
    ):
        # Initialize the internal providers
        self.providers = [
            SubSourceProvider(
                api_key=subsource_api_key, user_agent=user_agent, timeout=timeout
            ),
            SubDlProvider(
                api_key=subdl_api_key, user_agent=user_agent, timeout=timeout
            ),
        ]

    def download_and_parse(
        self,
        original_filename: str,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> Optional[List[srt.Subtitle]]:
        """
        Iterates through providers until subtitles are successfully
        found and parsed.
        """
        for provider in self.providers:
            provider_name = provider.__class__.__name__
            logger.info(f"Checking subtitles via {provider_name}...")

            try:
                result = provider.download_and_parse(
                    original_filename=original_filename,
                    imdb_id=imdb_id,
                    season=season,
                    episode=episode,
                )

                if result:
                    logger.info(
                        f"Successfully retrieved subtitles from {provider_name}"
                    )
                    return result

                logger.warning(f"{provider_name} returned no suitable subtitles.")

            except Exception as e:
                # Catching general exceptions here to ensure the loop continues
                # to the next provider even if one fails unexpectedly.
                logger.error(f"Unexpected error in {provider_name}: {e}")
                continue

        logger.error("All subtitle providers failed to find a match.")
        return None


class SubSourceProvider:
    def __init__(self, api_key: str, user_agent: str, timeout: int = 20):
        self.api_key = api_key
        self.user_agent = user_agent
        self.timeout = timeout
        self.api_base_url = "https://api.subsource.net"
        self.api_search_path = "/api/v1/movies/search"
        self.api_subtitles_path = "/api/v1/subtitles"
        self.api_download_path = "/api/v1/subtitles/{subtitle_id}/download"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> requests.Response:
        url = self.api_base_url + path
        for attempt in range(3):  # Max 3 attempts
            try:
                resp = self.session.request(
                    method, url, params=params, timeout=self.timeout, stream=stream
                )

                if resp.status_code in (401, 403):
                    logger.error("Invalid API key")
                    return resp

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    if attempt < 2:
                        logger.warning(f"⏳ Rate limited. Trying in {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    else:
                        logger.warning(f"❌ Rate limit exceeded after 3 tries.")
                        return resp

                if 500 <= resp.status_code < 600:
                    if attempt < 2:
                        backoff = [1, 3][attempt]
                        logger.warning(
                            f"Server error ({resp.status_code}). Retry {attempt + 1}/3..."
                        )
                        time.sleep(backoff)
                        continue
                    else:
                        logger.warning(
                            f"Server error ({resp.status_code}) after 3 retries."
                        )
                        return resp

                return resp

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ):
                if attempt < 2:
                    backoff = [0.5, 1.5][attempt]
                    logger.warning(
                        f"Timeout/Connection failed. Retry {attempt + 1}/3..."
                    )
                    time.sleep(backoff)
                else:
                    logger.warning("Failed to connect to SubSource after 3 attempts")

        # Return fallback pseudo-response (not strictly typed but caught upstream)
        err_resp = requests.Response()
        err_resp.status_code = 503
        return err_resp

    def _search_title(
        self, imdb_id: str, season: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"searchType": "imdb", "imdb": imdb_id}
        if season is not None:
            params["type"] = "series"
            params["season"] = season
        else:
            params["type"] = "movie"

        resp = self._request("GET", self.api_search_path, params=params)
        if not resp.ok:
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return cast(
                List[Dict[str, Any]], data.get("data") or data.get("items") or []
            )

        return []

    def _list_subtitles(
        self, content_id: int, language: str = "english"
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "movieId": content_id,
            "language": language,
            "limit": 100,
        }

        resp = self._request("GET", self.api_subtitles_path, params=params)
        if not resp.ok:
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return cast(
                List[Dict[str, Any]], data.get("data") or data.get("items") or []
            )

        return []

    def _download_subtitle(self, sub_id: int) -> Optional[bytes]:
        path = self.api_download_path.format(subtitle_id=sub_id)

        resp = self._request("GET", path, stream=True)
        if not resp.ok:
            return None

        return resp.content

    def download_and_parse(
        self,
        original_filename: str,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> Optional[List[srt.Subtitle]]:
        # search for the movie/series first to get the internal movie ID
        results = self._search_title(imdb_id, season)
        if not results:
            logger.info(f'No result for imdb_id:"{imdb_id}".')
            return None

        movie_id = results[0].get("movieId")
        if not movie_id:
            logger.warning("SubSource result missing 'movieId'.")
            return None

        subtitles = self._list_subtitles(movie_id)
        if not subtitles:
            logger.warning("No subtitles found on SubSource.net")
            return None

        best_subs = []
        for sub in subtitles:
            rel_info = sub.get("releaseInfo", [])
            rel_str = (
                str(rel_info[0])
                if isinstance(rel_info, list) and rel_info
                else str(rel_info)
            )
            sub = {
                "id": sub.get("subtitleId"),
                "file_name": rel_str,
                "original_file_name": original_filename,
            }
            best_subs.append(sub)

        best_subs.sort(key=score_subtitle, reverse=True)
        best_sub = best_subs[0] if best_subs and best_subs[0]["_score"] > 0 else None
        if not best_sub:
            logger.warning("No suitable subtitle found after scoring.")
            return None

        try:
            raw_data = self._download_subtitle(best_sub["id"])
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"Network error while download: {e}")
            return None

        if raw_data is None:
            logger.warning(f"Download subtitle failed.")
            return None

        if not raw_data:
            logger.warning(f"Download returns empty data.")
            return None

        # --- Detect ZIP vs SRT using magic bytes ---
        srt_data: Optional[bytes] = None
        if bytes(raw_data[0:4]) == b"PK\x03\x04":
            # It's a ZIP file
            srt_data = extract_srt_from_zip(raw_data, original_filename)
            if srt_data is None:
                logger.info("There are no .srt files in the downloaded ZIP.")
                return None
        else:
            # Assume it's raw SRT content
            srt_data = raw_data

        try:
            srt_sub = srt.parse(srt_data.decode("utf-8", errors="replace"))
            return list(srt_sub)
        except Exception as e:
            logger.error(f"Failed to parse SRT content: {e}")
            return None


class SubDlProvider:
    def __init__(self, api_key: str, user_agent: str, timeout: int = 20):
        self.api_key = api_key
        self.user_agent = user_agent
        self.timeout = timeout
        self.api_search_url = "https://api.subdl.com/api/v1/subtitles"
        self.api_download_url = "https://dl.subdl.com"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            }
        )
        # set the api key as a default param for all requests
        self.session.params = {"api_key": self.api_key}

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        expect_json: bool = True,
    ) -> requests.Response:
        for attempt in range(3):  # Max 3 attempts
            try:
                resp = self.session.request(
                    method, url, params=params, timeout=self.timeout, stream=stream
                )

                if resp.status_code in (401, 403):
                    logger.error("Invalid API key")
                    return resp

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    if attempt < 2:
                        logger.warning(f"⏳ Rate limited. Trying in {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    else:
                        logger.warning(f"❌ Rate limit exceeded after 3 tries.")
                        return resp

                if 500 <= resp.status_code < 600:
                    if attempt < 2:
                        backoff = [1, 3][attempt]
                        logger.warning(
                            f"Server error ({resp.status_code}). Retry {attempt + 1}/3..."
                        )
                        time.sleep(backoff)
                        continue
                    else:
                        logger.warning(
                            f"Server error ({resp.status_code}) after 3 retries."
                        )
                        return resp

                return resp

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as e:
                if attempt < 2:
                    backoff = [0.5, 1.5][attempt]
                    logger.warning(
                        f"Timeout/Connection failed. Retry {attempt + 1}/3..."
                    )
                    time.sleep(backoff)
                else:
                    logger.warning("Failed to connect to SubSource after 3 attempts")

        # Return fallback pseudo-response (not strictly typed but caught upstream)
        err_resp = requests.Response()
        err_resp.status_code = 503
        return err_resp

    def _list_subtitles(
        self,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        language: str = "EN",
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "imdb_id": imdb_id,
            "language": language,
            "subs_per_page": 30,
        }

        if season is not None and episode is not None:
            params["season_number"] = season
            params["episode_number"] = episode
            params["type"] = "tv"
        else:
            params["type"] = "movie"

        resp = self._request("GET", self.api_search_url, params=params)
        if not resp.ok:
            return []

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return cast(List[Dict[str, Any]], data.get("subtitles") or [])
        return []

    def _download_subtitle(self, sub_path: str) -> Optional[bytes]:
        url = self.api_download_url + sub_path

        resp = self._request("GET", url, stream=True, expect_json=False)
        if not resp.ok:
            logger.error(f"Download failed: HTTP {resp.status_code}")
            return None

        return resp.content

    def download_and_parse(
        self,
        original_filename: str,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> Optional[List[srt.Subtitle]]:
        subtitles = self._list_subtitles(imdb_id, season, episode)
        if not subtitles:
            logger.warning("No subtitles found on SubSource.net")
            return None

        best_subs = []
        for sub in subtitles:
            sub = {
                "url": sub.get("url"),
                "file_name": sub.get("release_name"),
                "original_file_name": original_filename,
            }
            best_subs.append(sub)

        best_subs.sort(key=score_subtitle, reverse=True)
        best_sub = best_subs[0] if best_subs and best_subs[0]["_score"] > 0 else None
        if not best_sub:
            logger.warning("No suitable subtitle found after scoring.")
            return None

        raw_data = self._download_subtitle(best_sub.get("url"))
        if not raw_data:
            logger.warning(f"Download returns empty data.")
            return None

        # --- Detect ZIP vs SRT using magic bytes ---
        srt_data: Optional[bytes] = None
        if bytes(raw_data[0:4]) == b"PK\x03\x04":
            # It's a ZIP file
            srt_data = extract_srt_from_zip(raw_data, original_filename)
            if srt_data is None:
                logger.info("There are no .srt files in the downloaded ZIP.")
                return None
        else:
            # Assume it's raw SRT content
            srt_data = raw_data

        try:
            srt_sub = srt.parse(srt_data.decode("utf-8", errors="replace"))
            return list(srt_sub)
        except Exception as e:
            logger.error(f"Failed to parse SRT content: {e}")
            return None


def score_subtitle(sub: Dict[str, Any]) -> float:
    try:
        original_filename = guessit(sub["original_file_name"])
        file_name = guessit(sub["file_name"])

        o_season = original_filename.get("season")
        o_episode = original_filename.get("episode")
        season = file_name.get("season")
        episode = file_name.get("episode")

        # logger.info(f"guessed original filename: {original_filename}")
        # logger.info(f"guessed subtitle filename: {file_name}")
        sub_score: float = 0.0
        # 1. Episode Match (+50/-50)
        if o_season and o_episode:
            if o_season == season and o_episode == episode:
                sub_score += 50.0
            else:
                sub_score -= 100.0

        # 2. Title Match — fuzzy similarity (up to +10)
        o_title = original_filename.get("title")
        title = file_name.get("title")
        if title and o_title:
            title_sim = difflib.SequenceMatcher(
                None, title.lower(), o_title.lower()
            ).ratio()
            sub_score += title_sim * 10.0

        # 3. Year match (+10)
        o_year = original_filename.get("year")
        year = file_name.get("year")
        if o_year and year and o_year == year:
            sub_score += 10.0

        o_quality = original_filename.get("source")
        quality = file_name.get("source")
        # 4. Quality Match (+10)
        if quality and o_quality and quality.lower() == o_quality.lower():
            sub_score += 10.0

        o_video_codec = original_filename.get("video_codec")
        video_codec = file_name.get("video_codec")
        # 5. Codec Match (+10)
        if (
            video_codec
            and o_video_codec
            and video_codec.lower() == o_video_codec.lower()
        ):
            sub_score += 10.0

        # 6. Release Group Match (+10)
        o_release_group = original_filename.get("release_group")
        release_group = file_name.get("release_group")
        if (
            release_group
            and o_release_group
            and release_group.lower() == o_release_group.lower()
        ):
            sub_score += 10.0

        # 7. Screen Size Match (+10)
        o_screen_size = original_filename.get("screen_size")
        screen_size = file_name.get("screen_size")
        if (
            screen_size
            and o_screen_size
            and screen_size.lower() == o_screen_size.lower()
        ):
            sub_score += 10.0

        # 8. Edition Match (+10)
        o_edition = original_filename.get("edition")
        edition = file_name.get("edition")
        if edition and o_edition and edition == o_edition:
            sub_score += 10.0

        # Tie-breaker: difflib similarity (0 to 1)
        sim: float = float(
            difflib.SequenceMatcher(
                None, sub["original_file_name"].lower(), sub["file_name"].lower()
            ).ratio()
        )

        # Save score for display/debugging
        final_score: float = sub_score + sim
        sub["_score"] = final_score

        return final_score
    except Exception as e:
        logger.warning(f"Score computation failed for {sub}: {e}")
        sub["_score"] = 0.0
        return 0.0


def extract_srt_from_zip(zip_bytes: bytes, original_filename: str) -> Optional[bytes]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        logger.error("The ZIP file is corrupt or not a valid ZIP.")
        return None

    srt_files = [
        name
        for name in zf.namelist()
        if name.lower().endswith(".srt") and not name.startswith("__MACOSX")
    ]

    if not srt_files:
        return None

    if len(srt_files) == 1:
        return zf.read(srt_files[0])

    # Multiple SRT files → pilih yang paling mirip nama dengan video
    def _score_extracted_srt(srt_name: str) -> float:
        srt_stem = Path(srt_name).stem
        score = 0.0
        language = guessit(srt_name).get("language")
        if not language:
            return score
        else:
            if babelfish.Language("eng") == language:
                score += 50.0
        sim = difflib.SequenceMatcher(
            None, original_filename.lower(), srt_stem.lower()
        ).ratio()
        return score + sim

    srt_files.sort(key=_score_extracted_srt, reverse=True)
    return zf.read(srt_files[0])
