from pathlib import Path

import pytest

from longforge import workspace as lf


def test_stock_provider_is_safe_with_license_metadata():
    media = {
        "provider": "pexels",
        "source_info": {
            "usage_status": "auto",
            "license": "Pexels License",
            "license_url": "https://www.pexels.com/license/",
            "rights_note": "Depicted third-party rights may still apply.",
        },
    }

    assessment = lf.youtube_safety(media)

    assert assessment["status"] == lf.YOUTUBE_SAFE
    assert assessment["caveat"]


def test_local_media_requires_review_until_rights_are_confirmed():
    media = {
        "provider": "local",
        "source_info": {
            "usage_status": "user-provided",
            "title": "my-file.mp4",
        },
    }

    assert lf.youtube_safety(media)["status"] == lf.YOUTUBE_REVIEW

    lf.set_rights_confirmed(media, True)

    assert lf.youtube_safety(media)["status"] == lf.YOUTUBE_SAFE


def test_restricted_license_is_blocked():
    media = {
        "provider": "wikimedia",
        "source_info": {
            "usage_status": "review",
            "license": "CC BY-NC 4.0",
            "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        },
    }

    assert lf.youtube_safety(media)["status"] == lf.YOUTUBE_BLOCK


def test_safe_mode_blocks_export_until_review_is_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "PROJECTS_DIR", tmp_path / "projects")
    source_file = tmp_path / "clip.mp4"
    source_file.write_bytes(b"test")

    project = lf.new_project("Copyright Gate Test")
    project["shots"] = [
        {
            "id": "shot-1",
            "order": 1,
            "narration": "Narration",
            "query": "test",
            "duration": 5.0,
            "notes": "",
            "candidates": [],
            "selected": {
                "provider": "local",
                "local_path": str(source_file),
                "source_info": {
                    "provider": "local",
                    "media_type": "video",
                    "usage_status": "user-provided",
                    "title": "clip.mp4",
                },
                "rights_confirmed": False,
            },
        }
    ]

    with pytest.raises(ValueError, match="YouTube Safe Mode blocked export"):
        lf.export_project(project)

    lf.set_rights_confirmed(project["shots"][0]["selected"], True)
    exported = lf.export_project(project)

    assert set(exported) == {"fcpxml", "credits", "manifest", "copyright"}
    assert all(Path(path).exists() for path in exported.values())
    assert "SAFE" in Path(exported["copyright"]).read_text(encoding="utf-8-sig")



def test_sync_shot_durations_matches_narration_total(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "PROJECTS_DIR", tmp_path / "projects")
    project = lf.new_project("Timing Test")
    project["narration_audio"] = {
        "filename": "voice.wav",
        "path": str(tmp_path / "voice.wav"),
        "duration": 30.0,
    }
    project["shots"] = [
        {
            "id": "a",
            "order": 1,
            "narration": "Short line.",
            "query": "a",
            "duration": 7.0,
            "notes": "",
            "candidates": [],
            "selected": None,
        },
        {
            "id": "b",
            "order": 2,
            "narration": "This second line is deliberately much longer than the first line.",
            "query": "b",
            "duration": 7.0,
            "notes": "",
            "candidates": [],
            "selected": None,
        },
    ]

    durations = lf.sync_shot_durations_to_narration(project)

    assert len(durations) == 2
    assert sum(durations) == pytest.approx(30.0, abs=0.01)
    assert project["shots"][0]["narration_start"] == pytest.approx(0.0)
    assert project["shots"][-1]["narration_end"] == pytest.approx(30.0, abs=0.01)
    assert project["shots"][1]["duration"] > project["shots"][0]["duration"]


def test_search_waves_are_limited_and_distinct_without_ai():
    waves = lf.build_search_waves(
        subject="Duchenne muscular dystrophy",
        query="dystrophin gene discovery",
        narration="In 1987 researchers identified the dystrophin gene in Duchenne.",
        use_ai=False,
    )

    assert 1 <= len(waves) <= 3
    assert len({item.lower() for item in waves}) == len(waves)
    assert waves[0] == "dystrophin gene discovery"


def test_source_in_is_clamped_and_exported_to_fcpxml(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "PROJECTS_DIR", tmp_path / "projects")
    source_file = tmp_path / "archive.mp4"
    source_file.write_bytes(b"placeholder")

    project = lf.new_project("Trim Test")
    project["youtube_safe_mode"] = False
    project["fps"] = 25
    shot = {
        "id": "shot-1",
        "order": 1,
        "narration": "Narration",
        "query": "archival research",
        "duration": 5.0,
        "notes": "",
        "candidates": [],
        "selected": {
            "provider": "pexels",
            "duration": 20.0,
            "local_path": str(source_file),
            "source_info": {
                "provider": "pexels",
                "media_type": "video",
                "usage_status": "auto",
                "license": "Pexels License",
            },
        },
    }
    project["shots"] = [shot]

    lf.set_source_in(shot, 18.0)

    assert shot["selected"]["source_in"] == pytest.approx(15.0)
    assert shot["selected"]["source_out"] == pytest.approx(20.0)

    xml = lf.build_fcpxml(project)

    assert 'start="375/25s"' in xml
    assert 'duration="125/25s"' in xml
