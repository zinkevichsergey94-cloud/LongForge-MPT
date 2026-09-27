import html
import re
from typing import Any, List
from urllib.parse import quote

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect


WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
ARCHIVE_SEARCH_API = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_API = "https://archive.org/metadata/{identifier}"

_USER_AGENT = (
    "LongForge-MediaScout/0.1 "
    "(https://github.com/zinkevichsergey94-cloud/LongForge-MPT)"
)


def _tls_verify() -> bool:
    value = config.app.get("tls_verify", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _request_json(url: str, *, params: dict | None = None, timeout=(20, 45)) -> Any:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": _USER_AGENT},
        proxies=config.proxy,
        verify=_tls_verify(),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _meta_value(metadata: dict, key: str) -> str:
    raw = metadata.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value")
    return _plain_text(raw)


def _license_status(name: str, url: str = "") -> str:
    """
    Conservative automatic-use policy.

    Public domain, CC0 and attribution-only Creative Commons works may be used
    automatically as long as attribution metadata is preserved. ShareAlike,
    NonCommercial, NoDerivatives and unknown licenses require review.
    """
    value = f"{name} {url}".lower()
    if not value.strip():
        return "reference"
    if any(token in value for token in ("public domain", "cc0", "pdm")):
        return "auto"
    if any(token in value for token in ("by-sa", "nc", "nd", "sharealike", "noncommercial", "noderivatives")):
        return "review"
    if re.search(r"creative\s*commons.*\bby\b", value) or re.search(r"/by/(?:[0-9.]+/)?", value):
        return "auto"
    if "cc by" in value:
        return "auto"
    return "reference"


def _aspect_matches(width: Any, height: Any, aspect: VideoAspect) -> bool:
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return True
    if width <= 0 or height <= 0:
        return True
    aspect = VideoAspect(aspect)
    if aspect == VideoAspect.square:
        return True
    return (width > height) if aspect == VideoAspect.landscape else (height > width)


def _source_info(
    *,
    provider: str,
    search_term: str,
    asset_id: str,
    source_page: str,
    title: str,
    description: str,
    media_type: str,
    license_name: str,
    license_url: str,
    creator: str = "",
    width: Any = None,
    height: Any = None,
    thumbnail: str = "",
) -> dict:
    return {
        "provider": provider,
        "search_term": search_term,
        "asset_id": asset_id,
        "source_page": source_page,
        "title": title,
        "description": description,
        "media_type": media_type,
        "license": license_name,
        "license_url": license_url,
        "usage_status": _license_status(license_name, license_url),
        "creator": {"name": creator} if creator else None,
        "thumbnail": thumbnail,
        "rendition": {
            "id": None,
            "width": width,
            "height": height,
        },
    }


def search_wikimedia(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.landscape,
) -> List[MaterialInfo]:
    """Search Wikimedia Commons files and return openly licensed images/videos."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": 6,
        "gsrsearch": search_term,
        "gsrlimit": 20,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 960,
        "iiextmetadatalanguage": "en",
        "iiextmetadatafilter": (
            "LicenseShortName|LicenseUrl|UsageTerms|Artist|Credit|ImageDescription"
        ),
    }
    logger.info(f"media scout Wikimedia search: term={search_term!r}")
    try:
        body = _request_json(WIKIMEDIA_API, params=params)
    except Exception as exc:
        logger.warning(
            "Wikimedia scout search failed: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return []

    pages = ((body or {}).get("query") or {}).get("pages") or {}
    items: List[MaterialInfo] = []
    for page in pages.values() if isinstance(pages, dict) else []:
        imageinfo = (page.get("imageinfo") or [None])[0]
        if not isinstance(imageinfo, dict):
            continue

        mime = str(imageinfo.get("mime") or "").lower()
        if mime.startswith("video/"):
            media_type = "video"
        elif mime.startswith("image/"):
            media_type = "image"
        else:
            continue

        width = imageinfo.get("width")
        height = imageinfo.get("height")
        if media_type == "image" and not _aspect_matches(width, height, video_aspect):
            continue

        ext = imageinfo.get("extmetadata") or {}
        license_name = (
            _meta_value(ext, "LicenseShortName")
            or _meta_value(ext, "UsageTerms")
        )
        license_url = _meta_value(ext, "LicenseUrl")
        usage_status = _license_status(license_name, license_url)
        if usage_status == "reference":
            continue

        source_url = str(imageinfo.get("url") or "")
        if not source_url.startswith(("http://", "https://")):
            continue

        title = str(page.get("title") or "").removeprefix("File:")
        description = _meta_value(ext, "ImageDescription")
        creator = _meta_value(ext, "Artist") or _meta_value(ext, "Credit")
        source_page = str(imageinfo.get("descriptionurl") or "")
        thumbnail = str(imageinfo.get("thumburl") or "")

        item = MaterialInfo()
        item.provider = "wikimedia"
        item.url = source_url
        item.duration = max(int(minimum_duration), 1)
        item.source_info = _source_info(
            provider="wikimedia",
            search_term=search_term,
            asset_id=str(page.get("pageid") or title),
            source_page=source_page,
            title=title,
            description=description,
            media_type=media_type,
            license_name=license_name,
            license_url=license_url,
            creator=creator,
            width=width,
            height=height,
            thumbnail=thumbnail,
        )
        items.append(item)

    logger.info(f"media scout Wikimedia results: term={search_term!r}, count={len(items)}")
    return items


def search_openverse(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.landscape,
) -> List[MaterialInfo]:
    """Search Openverse for openly licensed still images."""
    params = {
        "q": search_term,
        "page_size": 20,
        "mature": "false",
        # Commercial-use filtering removes the largest class of unusable results.
        # We still inspect each returned license and keep ND/SA items out of auto-use.
        "license_type": "commercial",
    }
    logger.info(f"media scout Openverse search: term={search_term!r}")
    try:
        body = _request_json(OPENVERSE_API, params=params)
    except Exception as exc:
        logger.warning(
            "Openverse scout search failed: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return []

    results = (body or {}).get("results") or []
    items: List[MaterialInfo] = []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        width = result.get("width")
        height = result.get("height")
        if not _aspect_matches(width, height, video_aspect):
            continue

        license_name = str(result.get("license") or "")
        license_version = str(result.get("license_version") or "")
        if license_version:
            license_name = f"{license_name} {license_version}".strip()
        license_url = str(result.get("license_url") or "")
        usage_status = _license_status(license_name, license_url)
        if usage_status == "reference":
            continue

        original = str(result.get("url") or "")
        if not original.startswith(("http://", "https://")):
            continue
        source_page = str(result.get("foreign_landing_url") or "")
        title = _plain_text(result.get("title"))
        creator = _plain_text(result.get("creator"))
        thumbnail = str(result.get("thumbnail") or "")

        item = MaterialInfo()
        item.provider = "openverse"
        item.url = original
        item.duration = max(int(minimum_duration), 1)
        item.source_info = _source_info(
            provider="openverse",
            search_term=search_term,
            asset_id=str(result.get("id") or original),
            source_page=source_page,
            title=title,
            description="",
            media_type="image",
            license_name=license_name,
            license_url=license_url,
            creator=creator,
            width=width,
            height=height,
            thumbnail=thumbnail,
        )
        items.append(item)

    logger.info(f"media scout Openverse results: term={search_term!r}, count={len(items)}")
    return items


def _archive_license_name(metadata: dict) -> tuple[str, str]:
    url = str(metadata.get("licenseurl") or metadata.get("license_url") or "")
    name = str(metadata.get("license") or metadata.get("rights") or "")
    if not name and url:
        name = url.rsplit("/", 2)[-2] if "/" in url else url
    return _plain_text(name), url


def _archive_file_url(identifier: str, name: str) -> str:
    return f"https://archive.org/download/{quote(identifier)}/{quote(name)}"


def search_internet_archive(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.landscape,
) -> List[MaterialInfo]:
    """
    Search Internet Archive movies and resolve a small number of direct MP4 files.

    Only records with a machine-readable permissive license are returned for
    automatic use. Unknown-rights archive items are intentionally skipped.
    """
    params = {
        "q": f'({search_term}) AND mediatype:movies',
        "fl[]": ["identifier", "title", "description", "licenseurl", "rights"],
        "rows": 6,
        "page": 1,
        "output": "json",
    }
    logger.info(f"media scout Internet Archive search: term={search_term!r}")
    try:
        body = _request_json(ARCHIVE_SEARCH_API, params=params)
    except Exception as exc:
        logger.warning(
            "Internet Archive scout search failed: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return []

    docs = (((body or {}).get("response") or {}).get("docs")) or []
    items: List[MaterialInfo] = []
    for doc in docs if isinstance(docs, list) else []:
        identifier = str(doc.get("identifier") or "")
        if not identifier:
            continue
        try:
            metadata_body = _request_json(
                ARCHIVE_METADATA_API.format(identifier=quote(identifier)),
                timeout=(20, 60),
            )
        except Exception as exc:
            logger.debug(
                "Internet Archive metadata lookup failed: "
                f"id={identifier}, error={type(exc).__name__}, detail={exc}"
            )
            continue

        metadata = (metadata_body or {}).get("metadata") or {}
        license_name, license_url = _archive_license_name(metadata)
        if _license_status(license_name, license_url) != "auto":
            continue

        files = (metadata_body or {}).get("files") or []
        preferred = None
        for entry in files if isinstance(files, list) else []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            fmt = str(entry.get("format") or "").lower()
            if not name.lower().endswith(".mp4"):
                continue
            if "mpeg4" in fmt or "h.264" in fmt or not preferred:
                preferred = entry
                if "mpeg4" in fmt:
                    break
        if not preferred:
            continue

        name = str(preferred.get("name") or "")
        title = _plain_text(metadata.get("title") or doc.get("title"))
        description = _plain_text(metadata.get("description") or doc.get("description"))
        creator = _plain_text(metadata.get("creator"))
        item = MaterialInfo()
        item.provider = "internet_archive"
        item.url = _archive_file_url(identifier, name)
        item.duration = max(int(minimum_duration), 1)
        item.source_info = _source_info(
            provider="internet_archive",
            search_term=search_term,
            asset_id=identifier,
            source_page=f"https://archive.org/details/{quote(identifier)}",
            title=title,
            description=description,
            media_type="video",
            license_name=license_name,
            license_url=license_url,
            creator=creator,
            width=None,
            height=None,
            thumbnail=f"https://archive.org/services/img/{quote(identifier)}",
        )
        items.append(item)

    logger.info(
        f"media scout Internet Archive results: term={search_term!r}, count={len(items)}"
    )
    return items


PUBLIC_SCOUT_PROVIDERS = {
    "wikimedia": search_wikimedia,
    "openverse": search_openverse,
    "internet_archive": search_internet_archive,
}
