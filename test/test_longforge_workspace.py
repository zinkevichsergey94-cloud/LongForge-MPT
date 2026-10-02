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
