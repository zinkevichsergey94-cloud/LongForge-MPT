from __future__ import annotations

import csv
import json
import math
import re
import shutil
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

from moviepy import AudioFileClip, VideoFileClip

from app.models.schema import MaterialInfo, VideoAspect
from app.services import material, subtitle, twelvelabs

PROJECT_SCHEMA = "longforge.documentary-workbench"
PROJECT_VERSION = 1
ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECTS_DIR = ROOT_DIR / "storage" / "longforge_projects"
SAFE_STOCK_PROVIDERS = {"pexels", "pixabay", "coverr"}
YOUTUBE_SAFE = "SAFE"
YOUTUBE_REVIEW = "REVIEW"
YOUTUBE_BLOCK = "DO NOT USE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(value: str, fallback: str = "project") -> str:
    value = re.sub(r"[^\w\-. ]+", " ", str(value or ""), flags=re.UNICODE)
    value = re.sub(r"\s+", "-", value.strip()).strip("-._")
    return (value[:80] or fallback).lower()


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / safe_slug(project_id, "project")


def project_file(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def list_projects() -> list[dict[str, str]]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, str]] = []
    for path in PROJECTS_DIR.glob("*/project.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        projects.append(
            {
                "id": str(data.get("id") or path.parent.name),
                "title": str(data.get("title") or path.parent.name),
                "updated_at": str(data.get("updated_at") or ""),
            }
        )
    projects.sort(key=lambda item: item["updated_at"], reverse=True)
    return projects


def new_project(title: str = "Untitled documentary", subject: str = "") -> dict[str, Any]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_id = f"{safe_slug(title, 'longforge')}-{stamp}"
    now = utc_now()
    return {
        "schema": PROJECT_SCHEMA,
        "version": PROJECT_VERSION,
        "id": project_id,
        "title": title.strip() or "Untitled documentary",
        "subject": subject.strip(),
        "script": "",
        "fps": 25,
        "aspect": VideoAspect.landscape.value,
        "youtube_safe_mode": True,
        "ai_query_expansion": True,
        "narration_audio": None,
        "created_at": now,
        "updated_at": now,
        "shots": [],
    }


def save_project(project: dict[str, Any]) -> Path:
    if project.get("schema") != PROJECT_SCHEMA:
        project["schema"] = PROJECT_SCHEMA
    project["version"] = PROJECT_VERSION
    project["updated_at"] = utc_now()
    target_dir = project_dir(str(project["id"]))
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "assets").mkdir(exist_ok=True)
    path = target_dir / "project.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def load_project(project_id: str) -> dict[str, Any]:
    path = project_file(project_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != PROJECT_SCHEMA:
        raise ValueError("Not a LongForge documentary-workbench project")
    return data


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def probe_audio_duration(path: str | Path) -> float:
    clip = AudioFileClip(str(path))
    try:
        return max(0.0, float(clip.duration or 0.0))
    finally:
        clip.close()


def probe_video_duration(path: str | Path) -> float:
    clip = VideoFileClip(str(path), audio=False)
    try:
        return max(0.0, float(clip.duration or 0.0))
    finally:
        clip.close()


def save_narration_audio(
    project: dict[str, Any], filename: str, payload: bytes
) -> dict[str, Any]:
    suffix = Path(filename or "narration.mp3").suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValueError("Unsupported narration audio type")
    audio_dir = project_dir(str(project["id"])) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    target = audio_dir / f"narration-{uuid4().hex[:8]}{suffix}"
    target.write_bytes(payload)
    duration = probe_audio_duration(target)
    if duration <= 0:
        target.unlink(missing_ok=True)
        raise ValueError("Could not read narration audio duration")
    project["narration_audio"] = {
        "filename": filename,
        "path": str(target.resolve()),
        "duration": round(duration, 3),
        "uploaded_at": utc_now(),
    }
    save_project(project)
    return project["narration_audio"]


def sync_shot_durations_to_narration(
    project: dict[str, Any], minimum_shot_duration: float = 2.0
) -> list[float]:
    shots = project.get("shots") or []
    audio = project.get("narration_audio") if isinstance(project.get("narration_audio"), dict) else {}
    total = float(audio.get("duration") or 0.0)
    if not shots or total <= 0:
        return []

    floor = min(max(float(minimum_shot_duration), 0.25), total / len(shots))
    remaining = max(0.0, total - floor * len(shots))
    weights = []
    for shot in shots:
        narration = re.sub(r"\s+", " ", str(shot.get("narration") or "")).strip()
        weights.append(max(1.0, float(len(narration))))
    total_weight = sum(weights) or float(len(shots))

    durations = [floor + remaining * (weight / total_weight) for weight in weights]
    if durations:
        durations[-1] += total - sum(durations)

    cursor = 0.0
    for shot, duration in zip(shots, durations):
        duration = max(0.25, float(duration))
        shot["duration"] = round(duration, 3)
        shot["narration_start"] = round(cursor, 3)
        cursor += duration
        shot["narration_end"] = round(cursor, 3)
        if isinstance(shot.get("selected"), dict):
            set_source_in(shot, float(shot["selected"].get("source_in") or 0.0))
    save_project(project)
    return [round(value, 3) for value in durations]


def _normalize_alignment_text(value: str) -> str:
    return re.sub(r"[^\w]+", "", str(value or "").lower(), flags=re.UNICODE)


def _parse_srt_timestamp(value: str) -> float:
    hours, minutes, rest = value.strip().split(":")
    seconds, millis = rest.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def _subtitle_segments_from_srt(path: str | Path) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for _, timing, text in subtitle.file_to_subtitles(str(path)):
        match = re.match(
            r"\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*"
            r"(\d{2}:\d{2}:\d{2},\d{3})",
            timing,
        )
        if not match:
            continue
        try:
            start = _parse_srt_timestamp(match.group(1))
            end = _parse_srt_timestamp(match.group(2))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        segments.append({"start": start, "end": end, "text": str(text or "").strip()})
    return segments


def apply_transcript_timing(
    project: dict[str, Any],
    segments: list[dict[str, Any]],
    total_duration: float,
) -> list[float]:
    shots = project.get("shots") or []
    total_duration = max(0.0, float(total_duration or 0.0))
    if not shots or not segments or total_duration <= 0:
        return []

    if len(segments) < len(shots):
        return sync_shot_durations_to_narration(project)

    spans: list[tuple[int, int]] = []
    cursor = 0
    for shot_index, shot in enumerate(shots):
        if shot_index == len(shots) - 1:
            spans.append((cursor, len(segments) - 1))
            cursor = len(segments)
            break

        target = _normalize_alignment_text(str(shot.get("narration") or ""))
        if not target:
            spans.append((cursor, cursor))
            cursor += 1
            continue

        best_end = cursor
        best_score = -1.0
        combined = ""
        max_end = min(len(segments), cursor + 14)
        for end_index in range(cursor, max_end):
            combined += _normalize_alignment_text(segments[end_index].get("text", ""))
            score = SequenceMatcher(None, target, combined).ratio()
            length_ratio = len(combined) / max(len(target), 1)
            if 0.45 <= length_ratio <= 1.8:
                score += 0.08
            if score > best_score:
                best_score = score
                best_end = end_index
            if len(combined) > max(len(target) * 2.0, len(target) + 120):
                break
        spans.append((cursor, best_end))
        cursor = min(best_end + 1, len(segments) - 1)

    boundaries = [0.0]
    for span_index, (_, end_index) in enumerate(spans[:-1]):
        current_end = float(segments[end_index]["end"])
        next_index = min(end_index + 1, len(segments) - 1)
        next_start = float(segments[next_index]["start"])
        boundary = (current_end + next_start) / 2.0 if next_start >= current_end else current_end
        boundary = max(boundaries[-1] + 0.05, min(boundary, total_duration))
        boundaries.append(boundary)
    boundaries.append(total_duration)

    durations: list[float] = []
    for index, shot in enumerate(shots):
        start = min(boundaries[index], total_duration)
        end = min(max(boundaries[index + 1], start + 0.05), total_duration)
        duration = max(0.05, end - start)
        shot["narration_start"] = round(start, 3)
        shot["narration_end"] = round(end, 3)
        shot["duration"] = round(duration, 3)
        shot["timing_source"] = "whisper"
        durations.append(duration)
        if isinstance(shot.get("selected"), dict):
            set_source_in(shot, float(shot["selected"].get("source_in") or 0.0))

    save_project(project)
    return [round(value, 3) for value in durations]


def precise_sync_shots_to_narration(project: dict[str, Any]) -> list[float]:
    audio = project.get("narration_audio") if isinstance(project.get("narration_audio"), dict) else {}
    audio_path = Path(str(audio.get("path") or ""))
    total_duration = float(audio.get("duration") or 0.0)
    if not audio_path.exists() or total_duration <= 0:
        return []
    timing_dir = project_dir(str(project["id"])) / "audio"
    timing_dir.mkdir(parents=True, exist_ok=True)
    srt_path = timing_dir / "narration-timing.srt"
    result = subtitle.create(
        str(audio_path),
        str(srt_path),
        word_level=False,
        log_details=False,
    )
    if result in (None, "") and not srt_path.exists():
        return []
    segments = _subtitle_segments_from_srt(srt_path)
    return apply_transcript_timing(project, segments, total_duration)


def split_script(script: str, max_chars: int = 420) -> list[str]:
    """Split narration into editor-friendly chunks while preserving paragraph intent."""
    text = str(script or "").strip()
    if not text:
        return []
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]
    chunks: list[str] = []
    sentence_re = re.compile(r"(?<=[.!?…])\s+")
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        current = ""
        for sentence in sentence_re.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
    return chunks


def default_query(narration: str, subject: str = "") -> str:
    narration = re.sub(r"[^\w\s\-']+", " ", narration, flags=re.UNICODE)
    words = [word for word in narration.split() if len(word) > 3]
    phrase = " ".join(words[:9])
    if subject and subject.lower() not in phrase.lower():
        phrase = f"{subject} {phrase}".strip()
    return phrase[:180]


def make_shots(script: str, subject: str = "", duration: float = 7.0) -> list[dict[str, Any]]:
    shots = []
    for index, narration in enumerate(split_script(script), start=1):
        shots.append(
            {
                "id": uuid4().hex[:10],
                "order": index,
                "narration": narration,
                "query": default_query(narration, subject),
                "duration": float(duration),
                "notes": "",
                "candidates": [],
                "selected": None,
            }
        )
    return shots


def normalize_shot_order(project: dict[str, Any]) -> None:
    for index, shot in enumerate(project.get("shots") or [], start=1):
        shot["order"] = index


def move_shot(project: dict[str, Any], shot_id: str, delta: int) -> None:
    shots = project.get("shots") or []
    index = next((i for i, shot in enumerate(shots) if shot.get("id") == shot_id), None)
    if index is None:
        return
    target = max(0, min(len(shots) - 1, index + int(delta)))
    if target == index:
        return
    shots[index], shots[target] = shots[target], shots[index]
    normalize_shot_order(project)


def material_to_dict(item: MaterialInfo) -> dict[str, Any]:
    source = item.source_info if isinstance(item.source_info, dict) else {}
    return {
        "provider": str(item.provider or source.get("provider") or ""),
        "url": str(item.url or ""),
        "duration": float(item.duration or 0),
        "source_info": source,
    }


def material_from_dict(data: dict[str, Any]) -> MaterialInfo:
    item = MaterialInfo()
    item.provider = str(data.get("provider") or "")
    item.url = str(data.get("url") or "")
    try:
        item.duration = int(float(data.get("duration") or 0))
    except (TypeError, ValueError):
        item.duration = 0
    source = data.get("source_info")
    item.source_info = source if isinstance(source, dict) else {}
    return item


def youtube_safety(media: dict[str, Any]) -> dict[str, Any]:
    """Conservative rights-screening helper. It is a workflow guardrail, not legal advice."""
    info = media.get("source_info") if isinstance(media.get("source_info"), dict) else {}
    provider = str(media.get("provider") or info.get("provider") or "").strip().lower()
    usage = str(info.get("usage_status") or "").strip().lower()
    license_name = str(info.get("license") or "").strip()
    license_url = str(info.get("license_url") or "").strip()
    license_text = f"{license_name} {license_url}".lower()
    rights_note = str(info.get("rights_note") or "").strip()
    rights_confirmed = bool(media.get("rights_confirmed"))

    def result(status: str, reason: str, *, attribution: bool = False) -> dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            "requires_attribution": attribution,
            "rights_confirmed": rights_confirmed,
            "caveat": rights_note,
        }

    if rights_confirmed and provider == "local":
        return result(YOUTUBE_SAFE, "User confirmed rights for this local asset.")

    if provider == "local":
        return result(
            YOUTUBE_REVIEW,
            "Local/user-provided media has no machine-verifiable license. Confirm your rights before export.",
        )

    blocked_terms = (
        "all rights reserved",
        "editorial use only",
        "noncommercial",
        "non-commercial",
        "noderivatives",
        "no derivatives",
        "cc-by-nc",
        "cc by-nc",
        "cc-by-nd",
        "cc by-nd",
        "/by-nc/",
        "/by-nd/",
    )
    if any(term in license_text for term in blocked_terms):
        return result(
            YOUTUBE_BLOCK,
            "License contains a restriction that is unsafe for the default commercial YouTube workflow.",
        )

    if usage in {"reference", "blocked", "restricted"}:
        return result(
            YOUTUBE_BLOCK,
            "Source metadata does not grant automatic reuse rights.",
        )

    if usage == "review" or "sharealike" in license_text or "by-sa" in license_text:
        if rights_confirmed:
            return result(
                YOUTUBE_SAFE,
                "License was manually reviewed and confirmed for this use.",
                attribution=True,
            )
        return result(
            YOUTUBE_REVIEW,
            "License has conditions that require manual review before export.",
            attribution=True,
        )

    if provider in SAFE_STOCK_PROVIDERS and usage == "auto":
        return result(
            YOUTUBE_SAFE,
            f"{provider.title()} candidate passed the provider-license search path.",
        )

    if any(term in license_text for term in ("public domain", "cc0", "pdm")):
        return result(YOUTUBE_SAFE, "Public-domain/CC0 metadata detected.")

    has_cc_by = (
        "cc by" in license_text
        or "creativecommons.org/licenses/by/" in license_text
        or "creative commons attribution" in license_text
    )
    if has_cc_by:
        return result(
            YOUTUBE_SAFE,
            "Attribution-only Creative Commons license detected.",
            attribution=True,
        )

    if usage == "auto" and license_name:
        return result(
            YOUTUBE_SAFE,
            "Media Scout marked this licensed source as automatically reusable.",
            attribution=True,
        )

    if rights_confirmed:
        return result(
            YOUTUBE_SAFE,
            "Rights/license were manually reviewed and confirmed for this use.",
            attribution=True,
        )

    return result(
        YOUTUBE_REVIEW,
        "Rights are not clear enough for automatic YouTube-safe export.",
    )


def annotate_youtube_safety(media: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(media)
    annotated["youtube_safety"] = youtube_safety(annotated)
    return annotated


def set_rights_confirmed(selected: dict[str, Any], confirmed: bool) -> None:
    selected["rights_confirmed"] = bool(confirmed)
    selected["youtube_safety"] = youtube_safety(selected)


def copyright_rows(project: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shot in selected_shots(project):
        selected = shot["selected"]
        assessment = youtube_safety(selected)
        info = selected.get("source_info") if isinstance(selected.get("source_info"), dict) else {}
        rows.append(
            {
                "shot": shot.get("order"),
                "status": assessment["status"],
                "reason": assessment["reason"],
                "rights_confirmed": assessment["rights_confirmed"],
                "requires_attribution": assessment["requires_attribution"],
                "caveat": assessment["caveat"],
                "provider": selected.get("provider") or info.get("provider") or "",
                "title": info.get("title", ""),
                "license": info.get("license", ""),
                "license_url": info.get("license_url", ""),
                "source_page": info.get("source_page", ""),
                "local_file": Path(str(selected.get("local_path") or "")).name,
            }
        )
    return rows


def copyright_summary(project: dict[str, Any]) -> dict[str, Any]:
    rows = copyright_rows(project)
    counts = {YOUTUBE_SAFE: 0, YOUTUBE_REVIEW: 0, YOUTUBE_BLOCK: 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    issues = [row for row in rows if row["status"] != YOUTUBE_SAFE]
    return {"counts": counts, "issues": issues, "rows": rows}


def build_copyright_csv(project: dict[str, Any]) -> str:
    rows = copyright_rows(project)
    fields = [
        "shot",
        "status",
        "reason",
        "rights_confirmed",
        "requires_attribution",
        "caveat",
        "provider",
        "title",
        "license",
        "license_url",
        "source_page",
        "local_file",
    ]
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _fallback_search_waves(subject: str, query: str, narration: str) -> list[str]:
    subject = re.sub(r"\s+", " ", str(subject or "")).strip()
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    narration = re.sub(r"\s+", " ", str(narration or "")).strip()
    waves: list[str] = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip()
        if value and value.lower() not in {item.lower() for item in waves}:
            waves.append(value[:220])

    add(query)
    add(" ".join(part for part in (subject, query) if part))

    years = re.findall(r"\b(?:18|19|20)\d{2}\b", narration)
    capitalized = re.findall(r"\b[A-ZА-ЯІЇЄҐ][\w'’.-]{3,}\b", narration)
    context_tokens = list(dict.fromkeys(years + capitalized))[:8]
    if context_tokens:
        add(" ".join(part for part in (subject, " ".join(context_tokens), query) if part))

    narration_words = [
        word
        for word in re.findall(r"[\w'’.-]+", narration)
        if len(word) >= 5
    ]
    if narration_words:
        add(" ".join(part for part in (subject, " ".join(narration_words[:10])) if part))
    return waves[:3]


def _ai_search_waves(subject: str, query: str, narration: str) -> list[str]:
    try:
        from app.services import llm

        prompt = (
            "Create exactly 3 concise ENGLISH media-search queries for a documentary shot. "
            "The queries must be visibly different: (1) exact event/person/object, "
            "(2) archival/historical wording, (3) broader context or documents/maps/science imagery. "
            "Return ONLY a JSON array of three strings, no markdown.\n"
            f"Topic: {subject}\nShot query: {query}\nNarration: {narration[:900]}"
        )
        raw = llm._generate_response(prompt)
        match = re.search(r"\[[\s\S]*?\]", str(raw))
        if not match:
            return []
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, list):
            return []
        return [
            re.sub(r"\s+", " ", str(item)).strip()[:220]
            for item in parsed
            if str(item).strip()
        ][:3]
    except Exception:
        return []


def build_search_waves(
    subject: str,
    query: str,
    narration: str = "",
    use_ai: bool = True,
) -> list[str]:
    ai_waves = _ai_search_waves(subject, query, narration) if use_ai else []
    fallback = _fallback_search_waves(subject, query, narration)
    waves: list[str] = []
    for item in [query, *ai_waves, *fallback]:
        normalized = re.sub(r"\s+", " ", str(item or "")).strip()
        if normalized and normalized.lower() not in {w.lower() for w in waves}:
            waves.append(normalized[:220])
    return waves[:3]


def search_candidates(
    *,
    subject: str,
    query: str,
    duration: float,
    aspect: str = VideoAspect.landscape.value,
    limit: int = 18,
    narration: str = "",
    use_ai_query_expansion: bool = True,
) -> list[dict[str, Any]]:
    minimum_duration = max(2, int(math.ceil(float(duration or 5))))
    waves = build_search_waves(
        subject=subject,
        query=query,
        narration=narration,
        use_ai=use_ai_query_expansion,
    )
    if not waves:
        return []

    per_wave = max(4, int(math.ceil(max(1, int(limit)) / len(waves))))
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for wave_index, wave_query in enumerate(waves, start=1):
        items = material.search_media_scout(
            search_term=wave_query,
            minimum_duration=minimum_duration,
            video_aspect=VideoAspect(aspect),
            video_subject=subject.strip(),
        )
        added_this_wave = 0
        for item in items:
            candidate = annotate_youtube_safety(material_to_dict(item))
            info = candidate.get("source_info") if isinstance(candidate.get("source_info"), dict) else {}
            asset_id = str(info.get("asset_id") or candidate.get("url") or "")
            key = (str(candidate.get("provider") or ""), asset_id)
            if key in seen:
                continue
            seen.add(key)
            info = dict(info)
            info["search_wave"] = wave_index
            info["wave_query"] = wave_query
            candidate["source_info"] = info
            merged.append(candidate)
            added_this_wave += 1
            if added_this_wave >= per_wave or len(merged) >= limit:
                break
        if len(merged) >= limit:
            break
    return merged[:limit]


def _copy_into_assets(source_path: Path, target_dir: Path, stem: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower() or ".mp4"
    target = target_dir / f"{safe_slug(stem, 'asset')}{suffix}"
    counter = 2
    while target.exists() and target.resolve() != source_path.resolve():
        target = target_dir / f"{safe_slug(stem, 'asset')}-{counter}{suffix}"
        counter += 1
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return target


def select_candidate(
    project: dict[str, Any],
    shot: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Download/render the chosen candidate and attach it to exactly one shot."""
    candidate_item = material_from_dict(candidate)
    target_dir = project_dir(str(project["id"])) / "assets"
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded = material._save_scout_item(
        candidate_item,
        str(target_dir),
        max(1, int(round(float(shot.get("duration") or 5)))),
    )
    if not downloaded:
        raise RuntimeError("The selected media could not be downloaded or rendered")
    local_path = Path(downloaded).resolve()
    if local_path.parent != target_dir.resolve():
        local_path = _copy_into_assets(local_path, target_dir, f"shot-{shot['order']:03d}")
    selected = dict(candidate)
    selected["local_path"] = str(local_path)
    selected["selected_at"] = utc_now()
    selected["source_in"] = 0.0
    selected["youtube_safety"] = youtube_safety(selected)
    shot["selected"] = selected
    save_project(project)
    return selected


def save_uploaded_asset(
    project: dict[str, Any],
    shot: dict[str, Any],
    filename: str,
    payload: bytes,
) -> dict[str, Any]:
    suffix = Path(filename or "asset.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png"}:
        raise ValueError("Unsupported local media type")
    assets_dir = project_dir(str(project["id"])) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / f"shot-{int(shot.get('order') or 0):03d}-{uuid4().hex[:8]}{suffix}"
    target.write_bytes(payload)
    media_type = "image" if suffix in {".jpg", ".jpeg", ".png"} else "video"
    actual_duration = (
        probe_video_duration(target) if media_type == "video" else float(shot.get("duration") or 5)
    )
    selected = {
        "provider": "local",
        "url": "",
        "duration": actual_duration,
        "source_info": {
            "provider": "local",
            "title": filename,
            "media_type": media_type,
            "usage_status": "user-provided",
        },
        "local_path": str(target.resolve()),
        "selected_at": utc_now(),
        "rights_confirmed": False,
        "source_in": 0.0,
    }
    selected["youtube_safety"] = youtube_safety(selected)
    shot["selected"] = selected
    save_project(project)
    return selected


def selected_shots(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [shot for shot in project.get("shots") or [] if isinstance(shot.get("selected"), dict)]


def set_source_in(shot: dict[str, Any], source_in: float) -> dict[str, Any] | None:
    selected = shot.get("selected") if isinstance(shot.get("selected"), dict) else None
    if not selected:
        return None
    info = selected.get("source_info") if isinstance(selected.get("source_info"), dict) else {}
    if str(info.get("media_type") or "video").lower() == "image":
        selected["source_in"] = 0.0
        selected["source_out"] = float(shot.get("duration") or 5)
        return selected

    try:
        start = max(0.0, float(source_in or 0.0))
    except (TypeError, ValueError):
        start = 0.0
    desired = max(0.25, float(shot.get("duration") or 5.0))
    try:
        source_duration = max(0.0, float(selected.get("duration") or 0.0))
    except (TypeError, ValueError):
        source_duration = 0.0
    if source_duration > 0:
        start = min(start, max(0.0, source_duration - min(desired, source_duration)))
        end = min(source_duration, start + desired)
        if end - start < desired and source_duration >= desired:
            start = max(0.0, source_duration - desired)
            end = source_duration
    else:
        end = start + desired
    selected["source_in"] = round(start, 3)
    selected["source_out"] = round(end, 3)
    return selected


def suggest_smart_trim(shot: dict[str, Any]) -> dict[str, Any] | None:
    selected = shot.get("selected") if isinstance(shot.get("selected"), dict) else None
    if not selected:
        return None
    info = selected.get("source_info") if isinstance(selected.get("source_info"), dict) else {}
    if str(info.get("media_type") or "video").lower() != "video":
        return None
    url = str(selected.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    query = " ".join(
        part.strip()
        for part in (
            str(shot.get("query") or ""),
            str(shot.get("notes") or ""),
            str(shot.get("narration") or ""),
        )
        if part.strip()
    )[:1200]
    suggestion = twelvelabs.suggest_clip_window(
        video_url=url,
        query=query,
        target_duration=float(shot.get("duration") or 7.0),
        source_duration=float(selected.get("duration") or 0.0) or None,
    )
    if not suggestion:
        return None
    set_source_in(shot, float(suggestion["start"]))
    selected["smart_trim_reason"] = suggestion.get("reason", "")
    return {
        "start": selected.get("source_in", 0.0),
        "end": selected.get("source_out"),
        "reason": selected.get("smart_trim_reason", ""),
    }


def _seconds_fraction(seconds: float, fps: int) -> str:
    frames = max(1, int(round(max(float(seconds), 0.001) * fps)))
    return f"{frames}/{fps}s"


def _path_to_file_uri(path: str) -> str:
    return Path(path).resolve().as_uri()


def build_fcpxml(project: dict[str, Any]) -> str:
    """Create a simple ordered FCPXML timeline that DaVinci Resolve can import."""
    fps = int(project.get("fps") or 25)
    width, height = VideoAspect(project.get("aspect") or VideoAspect.landscape.value).to_resolution()
    clips = selected_shots(project)
    total_seconds = sum(float(shot.get("duration") or 5) for shot in clips)

    fcpxml = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(fcpxml, "resources")
    format_id = "r1"
    ET.SubElement(
        resources,
        "format",
        id=format_id,
        name=f"LongForge-{width}x{height}-{fps}p",
        frameDuration=f"1/{fps}s",
        width=str(width),
        height=str(height),
    )

    narration_audio = (
        project.get("narration_audio")
        if isinstance(project.get("narration_audio"), dict)
        else None
    )
    narration_ref = None
    next_resource_id = 2
    if narration_audio:
        narration_path = Path(str(narration_audio.get("path") or ""))
        narration_duration = float(narration_audio.get("duration") or 0.0)
        if narration_path.exists() and narration_duration > 0:
            narration_ref = f"r{next_resource_id}"
            next_resource_id += 1
            ET.SubElement(
                resources,
                "asset",
                id=narration_ref,
                name=narration_path.name,
                src=_path_to_file_uri(str(narration_path)),
                start="0s",
                duration=_seconds_fraction(narration_duration, fps),
                hasAudio="1",
            )

    asset_refs: list[tuple[dict[str, Any], str]] = []
    for shot in clips:
        selected = shot["selected"]
        local_path = str(selected.get("local_path") or "")
        if not local_path:
            continue
        asset_id = f"r{next_resource_id}"
        next_resource_id += 1
        duration = float(shot.get("duration") or 5)
        info = selected.get("source_info") if isinstance(selected.get("source_info"), dict) else {}
        media_type = str(info.get("media_type") or "video")
        try:
            source_duration = max(
                duration,
                float(selected.get("duration") or 0.0),
                float(selected.get("source_out") or 0.0),
            )
        except (TypeError, ValueError):
            source_duration = duration
        attrs = {
            "id": asset_id,
            "name": Path(local_path).name,
            "src": _path_to_file_uri(local_path),
            "start": "0s",
            "duration": _seconds_fraction(source_duration, fps),
            "hasVideo": "1",
            "format": format_id,
        }
        if media_type != "image" and bool(selected.get("keep_source_audio", False)):
            attrs["hasAudio"] = "1"
        ET.SubElement(resources, "asset", **attrs)
        asset_refs.append((shot, asset_id))

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="LongForge")
    project_node = ET.SubElement(event, "project", name=str(project.get("title") or "LongForge"))
    sequence = ET.SubElement(
        project_node,
        "sequence",
        format=format_id,
        duration=_seconds_fraction(total_seconds or 1, fps),
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")
    offset_seconds = 0.0
    for shot, asset_id in asset_refs:
        duration = float(shot.get("duration") or 5)
        selected = shot["selected"]
        try:
            source_in = max(0.0, float(selected.get("source_in") or 0.0))
        except (TypeError, ValueError):
            source_in = 0.0
        clip = ET.SubElement(
            spine,
            "asset-clip",
            name=f"{int(shot.get('order') or 0):03d} {Path(str(shot['selected'].get('local_path') or '')).name}",
            ref=asset_id,
            offset=_seconds_fraction(offset_seconds, fps) if offset_seconds > 0 else "0s",
            start=_seconds_fraction(source_in, fps) if source_in > 0 else "0s",
            duration=_seconds_fraction(duration, fps),
        )
        narration = str(shot.get("narration") or "").strip()
        if narration:
            marker = ET.SubElement(clip, "marker", start="0s", value=narration[:250])
            marker.set("completed", "0")

        if narration_ref is not None:
            try:
                narration_start = max(
                    0.0,
                    float(shot.get("narration_start") or offset_seconds),
                )
            except (TypeError, ValueError):
                narration_start = offset_seconds
            ET.SubElement(
                clip,
                "asset-clip",
                name="Narration",
                ref=narration_ref,
                lane="-1",
                start=(
                    _seconds_fraction(narration_start, fps)
                    if narration_start > 0
                    else "0s"
                ),
                duration=_seconds_fraction(duration, fps),
                audioRole="dialogue",
            )
        offset_seconds += duration

    body = ET.tostring(fcpxml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + body + "\n"


def attribution_rows(project: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shot in selected_shots(project):
        selected = shot["selected"]
        info = selected.get("source_info") if isinstance(selected.get("source_info"), dict) else {}
        creator = info.get("creator") if isinstance(info.get("creator"), dict) else {}
        rows.append(
            {
                "shot": shot.get("order"),
                "provider": selected.get("provider") or info.get("provider"),
                "title": info.get("title", ""),
                "creator": creator.get("name", ""),
                "license": info.get("license", ""),
                "license_url": info.get("license_url", ""),
                "source_page": info.get("source_page", ""),
                "usage_status": info.get("usage_status", ""),
                "youtube_status": youtube_safety(selected)["status"],
                "youtube_reason": youtube_safety(selected)["reason"],
                "rights_note": youtube_safety(selected)["caveat"],
                "rights_confirmed": youtube_safety(selected)["rights_confirmed"],
                "local_file": Path(str(selected.get("local_path") or "")).name,
                "query": shot.get("query", ""),
            }
        )
    return rows


def build_attribution_csv(project: dict[str, Any]) -> str:
    rows = attribution_rows(project)
    fields = [
        "shot",
        "provider",
        "title",
        "creator",
        "license",
        "license_url",
        "source_page",
        "usage_status",
        "youtube_status",
        "youtube_reason",
        "rights_note",
        "rights_confirmed",
        "local_file",
        "query",
    ]
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def export_project(project: dict[str, Any]) -> dict[str, Path]:
    save_project(project)
    if bool(project.get("youtube_safe_mode", True)):
        summary = copyright_summary(project)
        if summary["issues"]:
            shot_numbers = ", ".join(str(row["shot"]) for row in summary["issues"][:12])
            raise ValueError(
                "YouTube Safe Mode blocked export. Review or replace flagged media "
                f"in shot(s): {shot_numbers}."
            )
    export_dir = project_dir(str(project["id"])) / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    base = safe_slug(str(project.get("title") or "longforge"), "longforge")
    fcpxml_path = export_dir / f"{base}.fcpxml"
    credits_path = export_dir / f"{base}-sources.csv"
    manifest_path = export_dir / f"{base}-timeline.json"
    copyright_path = export_dir / f"{base}-copyright-report.csv"
    narration_export_path = None
    narration_audio = (
        project.get("narration_audio")
        if isinstance(project.get("narration_audio"), dict)
        else None
    )
    if narration_audio:
        source_audio = Path(str(narration_audio.get("path") or ""))
        if source_audio.exists() and source_audio.is_file():
            narration_export_path = export_dir / (
                f"{base}-narration{source_audio.suffix.lower() or '.wav'}"
            )
            if source_audio.resolve() != narration_export_path.resolve():
                shutil.copy2(source_audio, narration_export_path)

    fcpxml_path.write_text(build_fcpxml(project), encoding="utf-8")
    credits_path.write_text(build_attribution_csv(project), encoding="utf-8-sig")
    copyright_path.write_text(build_copyright_csv(project), encoding="utf-8-sig")
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "longforge.timeline-manifest",
                "version": 1,
                "project": project.get("title"),
                "fps": project.get("fps"),
                "aspect": project.get("aspect"),
                "narration_audio": project.get("narration_audio"),
                "shots": [
                    {
                        "order": shot.get("order"),
                        "narration": shot.get("narration"),
                        "query": shot.get("query"),
                        "duration": shot.get("duration"),
                        "media": shot.get("selected"),
                    }
                    for shot in selected_shots(project)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    exported = {
        "fcpxml": fcpxml_path,
        "credits": credits_path,
        "manifest": manifest_path,
        "copyright": copyright_path,
    }
    if narration_export_path is not None:
        exported["narration"] = narration_export_path
    return exported
