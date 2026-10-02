from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) in sys.path:
    sys.path.remove(str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR))

from app.models.schema import VideoAspect  # noqa: E402
from longforge import workspace as lf  # noqa: E402

st.set_page_config(
    page_title="LongForge Workbench",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root { color-scheme: dark; }
.block-container { padding-top: 1.2rem; max-width: 1700px; }
[data-testid="stSidebar"] { min-width: 290px; }
.lf-kicker { color:#9aa4b2; letter-spacing:.08em; font-size:.78rem; text-transform:uppercase; }
.lf-title { font-size:2rem; font-weight:750; line-height:1.1; margin-bottom:.25rem; }
.lf-muted { color:#98a2b3; }
.lf-shot { border:1px solid rgba(255,255,255,.10); border-radius:14px; padding:.9rem 1rem; margin:.45rem 0; }
.lf-picked { border-color:rgba(88,166,255,.55); background:rgba(88,166,255,.06); }
</style>
""",
    unsafe_allow_html=True,
)


def ensure_project() -> dict:
    if "lf_project" not in st.session_state:
        projects = lf.list_projects()
        if projects:
            try:
                st.session_state.lf_project = lf.load_project(projects[0]["id"])
            except Exception:
                st.session_state.lf_project = lf.new_project("LongForge documentary")
        else:
            st.session_state.lf_project = lf.new_project("LongForge documentary")
    return st.session_state.lf_project


def persist() -> None:
    lf.save_project(st.session_state.lf_project)


def load_selected(project_id: str) -> None:
    st.session_state.lf_project = lf.load_project(project_id)
    st.session_state.lf_last_export = None


def candidate_label(candidate: dict) -> tuple[str, str, str, str, str]:
    info = candidate.get("source_info") if isinstance(candidate.get("source_info"), dict) else {}
    provider = str(candidate.get("provider") or info.get("provider") or "unknown")
    title = str(info.get("title") or info.get("description") or "Untitled asset").strip()
    license_name = str(info.get("license") or "provider license")
    usage = str(info.get("usage_status") or "unknown")
    thumb = str(info.get("thumbnail") or "")
    return provider, title, license_name, usage, thumb


project = ensure_project()

with st.sidebar:
    st.markdown('<div class="lf-kicker">LongForge</div>', unsafe_allow_html=True)
    st.markdown("## Documentary Workbench")
    st.caption("Script → shot research → selection → timeline → DaVinci")

    existing = lf.list_projects()
    if existing:
        options = {
            f"{item['title']} · {item['updated_at'][:10]}": item["id"]
            for item in existing
        }
        current_id = str(project.get("id") or "")
        if current_id not in options.values():
            options = {
                f"{project.get('title') or 'New project'} · unsaved": current_id,
                **options,
            }
        current_label = next(
            label for label, pid in options.items() if pid == current_id
        )
        selected_label = st.selectbox(
            "Projects", list(options), index=list(options).index(current_label)
        )
        if options[selected_label] != current_id:
            load_selected(options[selected_label])
            st.rerun()

    if st.button("＋ New project", use_container_width=True):
        st.session_state.lf_project = lf.new_project("New LongForge documentary")
        st.session_state.lf_last_export = None
        st.rerun()

    st.divider()
    project["title"] = st.text_input(
        "Project title", value=str(project.get("title") or "")
    )
    project["subject"] = st.text_input(
        "Subject / topic",
        value=str(project.get("subject") or ""),
        help="Used to make archive searches more specific.",
    )
    aspects = [
        VideoAspect.landscape.value,
        VideoAspect.portrait.value,
        VideoAspect.square.value,
    ]
    project["aspect"] = st.selectbox(
        "Aspect",
        aspects,
        index=aspects.index(
            project.get("aspect") or VideoAspect.landscape.value
        ),
    )
    fps_options = [24, 25, 30]
    project["fps"] = int(
        st.selectbox(
            "Timeline FPS",
            fps_options,
            index=fps_options.index(int(project.get("fps") or 25)),
        )
    )
    project["youtube_safe_mode"] = st.toggle(
        "YouTube Safe Mode",
        value=bool(project.get("youtube_safe_mode", True)),
        help=(
            "When enabled, DaVinci export is blocked if any selected media is "
            "DO NOT USE or still requires manual rights review."
        ),
    )
    project["ai_query_expansion"] = st.toggle(
        "AI query expansion",
        value=bool(project.get("ai_query_expansion", True)),
        help=(
            "When the configured LLM is available, create several different English "
            "search phrases for each documentary shot. Falls back to local query variants."
        ),
    )
    if st.button("Save project", type="primary", use_container_width=True):
        persist()
        st.toast("Project saved")

selected_count = len(lf.selected_shots(project))
shot_count = len(project.get("shots") or [])

st.markdown(
    '<div class="lf-kicker">LONGFORGE / NEW WORKFLOW</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="lf-title">{project.get("title") or "Untitled documentary"}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="lf-muted">{shot_count} shots · {selected_count} media selected · '
    "no automatic faceless-video assembly</div>",
    unsafe_allow_html=True,
)

script_tab, scout_tab, timeline_tab, export_tab = st.tabs(
    [
        "1 · Script & shots",
        "2 · Media Scout",
        "3 · Timeline",
        "4 · DaVinci export",
    ]
)

with script_tab:
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        st.subheader("Narration")
        project["script"] = st.text_area(
            "Full script",
            value=str(project.get("script") or ""),
            height=330,
            label_visibility="collapsed",
            placeholder=(
                "Paste the documentary narration here. Blank lines are treated "
                "as strong scene boundaries."
            ),
        )
        c1, c2 = st.columns(2)
        with c1:
            default_duration = st.number_input(
                "Default shot length (s)", 2.0, 30.0, 7.0, 0.5
            )
        with c2:
            replace = st.checkbox(
                "Replace existing shots",
                value=not bool(project.get("shots")),
            )
        if st.button(
            "Build editable shots", type="primary", use_container_width=True
        ):
            generated = lf.make_shots(
                project["script"],
                project.get("subject", ""),
                default_duration,
            )
            if not generated:
                st.warning("Add narration first.")
            elif project.get("shots") and not replace:
                project["shots"].extend(generated)
                lf.normalize_shot_order(project)
                persist()
                st.rerun()
            else:
                project["shots"] = generated
                persist()
                st.rerun()

        st.divider()
        st.subheader("Narration timing")
        narration_audio = project.get("narration_audio") if isinstance(project.get("narration_audio"), dict) else None
        if narration_audio:
            st.success(
                f"Narration loaded · {float(narration_audio.get('duration') or 0):.1f}s · "
                f"{narration_audio.get('filename') or 'audio'}"
            )
        audio_upload = st.file_uploader(
            "Upload final narration",
            type=["mp3", "wav", "m4a", "aac", "flac", "ogg"],
            key="lf_narration_audio",
            help="LongForge reads the real audio duration and can fit the shot plan to it.",
        )
        audio_col, sync_col, precise_col = st.columns(3)
        with audio_col:
            if audio_upload is not None and st.button(
                "Use this narration", use_container_width=True
            ):
                try:
                    lf.save_narration_audio(
                        project,
                        audio_upload.name,
                        audio_upload.getvalue(),
                    )
                    st.toast("Narration timing loaded")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not read narration: {exc}")
        with sync_col:
            if st.button(
                "Quick sync",
                use_container_width=True,
                disabled=not bool(narration_audio) or not bool(project.get("shots")),
                help="Fast proportional timing using the real narration duration.",
            ):
                durations = lf.sync_shot_durations_to_narration(project)
                if durations:
                    st.toast("Shot timings aligned to narration")
                    st.rerun()
        with precise_col:
            if st.button(
                "Precise local timing",
                use_container_width=True,
                disabled=not bool(narration_audio) or not bool(project.get("shots")),
                help="Uses local faster-whisper to follow real speech and pauses. No API charge.",
            ):
                with st.spinner("Analyzing narration locally with Whisper…"):
                    durations = lf.precise_sync_shots_to_narration(project)
                if durations:
                    st.toast("Precise narration timing applied")
                    st.rerun()
                else:
                    st.warning(
                        "Precise timing was unavailable. Quick sync is still usable."
                    )
    with right:
        st.subheader("What this version does")
        st.markdown(
            """
- You control the narration and shot boundaries.
- Each shot gets its own search request, not a global bag of keywords.
- Search results stay visible so you choose the actual archive/stock item.
- Selected files are saved with source/license metadata.
- The final ordered sequence is exported for DaVinci Resolve.
            """
        )
        st.info(
            "AI ranking is a helper. It does not silently choose and assemble "
            "the documentary for you."
        )

    if project.get("shots"):
        st.divider()
        st.subheader("Shot plan")
        for shot in project["shots"]:
            picked = isinstance(shot.get("selected"), dict)
            status = "✓ media selected" if picked else "needs media"
            with st.expander(
                f"Shot {shot['order']:03d} · {status}",
                expanded=False,
            ):
                shot["narration"] = st.text_area(
                    "Narration",
                    value=str(shot.get("narration") or ""),
                    key=f"narr_{shot['id']}",
                    height=110,
                )
                shot["query"] = st.text_input(
                    "Search query",
                    value=str(shot.get("query") or ""),
                    key=f"query_{shot['id']}",
                )
                a, b = st.columns([0.25, 0.75])
                with a:
                    shot["duration"] = st.number_input(
                        "Seconds",
                        1.0,
                        60.0,
                        float(shot.get("duration") or 7),
                        0.5,
                        key=f"dur_{shot['id']}",
                    )
                with b:
                    shot["notes"] = st.text_input(
                        "Visual direction / notes",
                        value=str(shot.get("notes") or ""),
                        key=f"notes_{shot['id']}",
                    )
                timing_start = shot.get("narration_start")
                timing_end = shot.get("narration_end")
                if timing_start is not None and timing_end is not None:
                    timing_source = str(shot.get("timing_source") or "quick")
                    st.caption(
                        f"Narration timing: {float(timing_start):.2f}s → "
                        f"{float(timing_end):.2f}s · {timing_source}"
                    )
                if picked:
                    selected = shot["selected"]
                    st.caption(
                        "Selected: "
                        + Path(str(selected.get("local_path") or "")).name
                    )
        if st.button("Save shot edits", use_container_width=True):
            persist()
            st.toast("Shot plan saved")

with scout_tab:
    if not project.get("shots"):
        st.info("Build shots from the script first.")
    else:
        shot_labels = {
            f"{shot['order']:03d} · "
            f"{str(shot.get('narration') or '')[:80]}": shot["id"]
            for shot in project["shots"]
        }
        label = st.selectbox("Shot", list(shot_labels))
        shot = next(
            item
            for item in project["shots"]
            if item["id"] == shot_labels[label]
        )
        st.markdown(f"**Narration:** {shot.get('narration')}")
        query_col, button_col = st.columns([0.8, 0.2])
        with query_col:
            shot["query"] = st.text_input(
                "Search request",
                value=str(shot.get("query") or ""),
                key=f"scout_query_{shot['id']}",
            )
        with button_col:
            st.write("")
            st.write("")
            run_search = st.button(
                "Search media",
                type="primary",
                use_container_width=True,
            )
        if run_search:
            if not shot["query"].strip():
                st.warning("Add a search request.")
            else:
                with st.spinner(
                    "Searching stock + Wikimedia + Openverse + Internet Archive…"
                ):
                    try:
                        shot["candidates"] = lf.search_candidates(
                            subject=str(project.get("subject") or ""),
                            query=shot["query"],
                            duration=float(shot.get("duration") or 7),
                            aspect=str(
                                project.get("aspect")
                                or VideoAspect.landscape.value
                            ),
                            limit=18,
                            narration=str(shot.get("narration") or ""),
                            use_ai_query_expansion=bool(project.get("ai_query_expansion", True)),
                        )
                        persist()
                    except Exception as exc:
                        st.error(f"Search failed: {exc}")

        candidates = shot.get("candidates") or []
        if not candidates:
            st.caption("No candidates stored for this shot yet.")
        else:
            st.caption(
                f"{len(candidates)} candidates. Pick the exact item you want "
                "on the timeline."
            )
            for row_start in range(0, len(candidates), 3):
                cols = st.columns(3, gap="medium")
                row_candidates = candidates[row_start : row_start + 3]
                for offset, (col, candidate) in enumerate(
                    zip(cols, row_candidates)
                ):
                    candidate_index = row_start + offset
                    with col:
                        (
                            provider,
                            title,
                            license_name,
                            usage,
                            thumb,
                        ) = candidate_label(candidate)
                        st.markdown(f"**{title[:100]}**")
                        assessment = lf.youtube_safety(candidate)
                        status = assessment["status"]
                        if status == lf.YOUTUBE_SAFE:
                            st.success(f"SAFE · {assessment['reason']}")
                        elif status == lf.YOUTUBE_REVIEW:
                            st.warning(f"REVIEW · {assessment['reason']}")
                        else:
                            st.error(f"DO NOT USE · {assessment['reason']}")
                        if assessment.get("caveat"):
                            st.caption(f"Rights caveat: {assessment['caveat']}")
                        st.caption(
                            f"{provider} · {license_name} · {usage}"
                        )
                        if thumb.startswith("http"):
                            try:
                                st.image(
                                    thumb,
                                    use_container_width=True,
                                )
                            except Exception:
                                pass
                        info = (
                            candidate.get("source_info")
                            if isinstance(candidate.get("source_info"), dict)
                            else {}
                        )
                        wave = info.get("search_wave")
                        wave_query = str(info.get("wave_query") or "")
                        if wave:
                            st.caption(f"Search wave {wave}: {wave_query}")
                        source_page = str(info.get("source_page") or "")
                        if source_page.startswith("http"):
                            st.link_button(
                                "Source page",
                                source_page,
                                use_container_width=True,
                            )
                        if st.button(
                            "Use this shot",
                            key=f"pick_{shot['id']}_{candidate_index}",
                            use_container_width=True,
                            disabled=(status == lf.YOUTUBE_BLOCK),
                        ):
                            with st.spinner("Downloading selected media…"):
                                try:
                                    lf.select_candidate(
                                        project,
                                        shot,
                                        candidate,
                                    )
                                    st.toast("Added to timeline")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(
                                        f"Could not use this media: {exc}"
                                    )

        st.divider()
        uploaded = st.file_uploader(
            "Or use your own file for this shot",
            type=[
                "mp4",
                "mov",
                "mkv",
                "webm",
                "jpg",
                "jpeg",
                "png",
            ],
            key=f"upload_{shot['id']}",
        )
        if uploaded is not None and st.button(
            "Use uploaded file",
            key=f"upload_btn_{shot['id']}",
        ):
            lf.save_uploaded_asset(
                project,
                shot,
                uploaded.name,
                uploaded.getvalue(),
            )
            st.toast("Local media added")
            st.rerun()

with timeline_tab:
    shots = project.get("shots") or []
    if not shots:
        st.info("No shots yet.")
    else:
        total = sum(
            float(shot.get("duration") or 0)
            for shot in shots
            if shot.get("selected")
        )
        st.subheader(f"Ordered visual track · {total:.1f}s selected")
        for shot in shots:
            selected = (
                shot.get("selected")
                if isinstance(shot.get("selected"), dict)
                else None
            )
            info = (
                selected.get("source_info")
                if selected
                and isinstance(selected.get("source_info"), dict)
                else {}
            )
            filename = (
                Path(str(selected.get("local_path") or "")).name
                if selected
                else "—"
            )
            provider = (
                str(
                    selected.get("provider")
                    or info.get("provider")
                    or ""
                )
                if selected
                else ""
            )
            assessment = lf.youtube_safety(selected) if selected else None
            safety_label = f" · {assessment['status']}" if assessment else ""
            cls = "lf-shot lf-picked" if selected else "lf-shot"
            st.markdown(
                f'<div class="{cls}"><b>{shot["order"]:03d}</b> · '
                f'{float(shot.get("duration") or 0):.1f}s · '
                f'{provider or "NO MEDIA"}{safety_label}<br>'
                f'<span class="lf-muted">{filename}</span><br>'
                f'{str(shot.get("narration") or "")[:180]}</div>',
                unsafe_allow_html=True,
            )
            if selected:
                media_type = str(info.get("media_type") or "video").lower()
                if media_type == "video":
                    try:
                        source_duration = max(0.0, float(selected.get("duration") or 0.0))
                    except (TypeError, ValueError):
                        source_duration = 0.0
                    shot_duration = max(0.25, float(shot.get("duration") or 5.0))
                    max_start = max(0.0, source_duration - min(source_duration, shot_duration)) if source_duration > 0 else 36000.0
                    current_start = max(0.0, float(selected.get("source_in") or 0.0))
                    current_start = min(current_start, max_start)
                    trim_a, trim_b, trim_c = st.columns([0.34, 0.33, 0.33])
                    with trim_a:
                        new_source_in = st.number_input(
                            "Source in (s)",
                            min_value=0.0,
                            max_value=float(max_start),
                            value=float(current_start),
                            step=0.5,
                            key=f"source_in_{shot['id']}",
                        )
                        if abs(new_source_in - current_start) > 0.0001:
                            lf.set_source_in(shot, new_source_in)
                            persist()
                            st.rerun()
                    with trim_b:
                        derived = lf.set_source_in(shot, current_start) or selected
                        st.metric(
                            "Source out",
                            f"{float(derived.get('source_out') or shot_duration):.1f}s",
                        )
                    with trim_c:
                        if lf.twelvelabs.is_enabled() and str(selected.get("url") or "").startswith(("http://", "https://")):
                            if st.button(
                                "AI Smart Trim",
                                key=f"smart_trim_{shot['id']}",
                                use_container_width=True,
                            ):
                                with st.spinner("Finding the strongest moment inside the source…"):
                                    suggestion = lf.suggest_smart_trim(shot)
                                if suggestion:
                                    persist()
                                    st.toast(
                                        f"Smart Trim: {suggestion['start']:.1f}s → {suggestion['end']:.1f}s"
                                    )
                                    st.rerun()
                                else:
                                    st.warning("No reliable smart-trim window was returned.")
                        else:
                            st.caption("Smart Trim optional · TwelveLabs key not configured")
                    if selected.get("smart_trim_reason"):
                        st.caption(f"Smart Trim reason: {selected['smart_trim_reason']}")
                    keep_source_audio = st.checkbox(
                        "Keep original source audio in DaVinci",
                        value=bool(selected.get("keep_source_audio", False)),
                        key=f"keep_source_audio_{shot['id']}",
                        help=(
                            "Off by default so B-roll does not compete with narration. "
                            "Enable only when the original archive sound is useful."
                        ),
                    )
                    if keep_source_audio != bool(selected.get("keep_source_audio", False)):
                        selected["keep_source_audio"] = keep_source_audio
                        persist()
                        st.rerun()

            if selected and assessment:
                if assessment["status"] == lf.YOUTUBE_SAFE:
                    st.success(assessment["reason"])
                    if assessment.get("caveat"):
                        st.caption(f"Rights caveat: {assessment['caveat']}")
                elif assessment["status"] == lf.YOUTUBE_REVIEW:
                    st.warning(assessment["reason"])
                    confirmed = st.checkbox(
                        "I verified that I have the rights/license to use this media on YouTube",
                        value=bool(selected.get("rights_confirmed")),
                        key=f"rights_{shot['id']}",
                    )
                    if confirmed != bool(selected.get("rights_confirmed")):
                        lf.set_rights_confirmed(selected, confirmed)
                        persist()
                        st.rerun()
                else:
                    st.error(assessment["reason"])
            a, b, c = st.columns([0.12, 0.12, 0.76])
            with a:
                if st.button(
                    "↑",
                    key=f"up_{shot['id']}",
                    disabled=shot["order"] <= 1,
                ):
                    lf.move_shot(project, shot["id"], -1)
                    persist()
                    st.rerun()
            with b:
                if st.button(
                    "↓",
                    key=f"down_{shot['id']}",
                    disabled=shot["order"] >= len(shots),
                ):
                    lf.move_shot(project, shot["id"], 1)
                    persist()
                    st.rerun()
            with c:
                if selected and st.button(
                    "Remove selected media",
                    key=f"clear_{shot['id']}",
                ):
                    shot["selected"] = None
                    persist()
                    st.rerun()

with export_tab:
    selected = lf.selected_shots(project)
    missing = len(project.get("shots") or []) - len(selected)
    copyright_summary = lf.copyright_summary(project)
    counts = copyright_summary["counts"]
    st.subheader("DaVinci handoff")
    m1, m2, m3 = st.columns(3)
    m1.metric("SAFE", counts.get(lf.YOUTUBE_SAFE, 0))
    m2.metric("REVIEW", counts.get(lf.YOUTUBE_REVIEW, 0))
    m3.metric("DO NOT USE", counts.get(lf.YOUTUBE_BLOCK, 0))
    if bool(project.get("youtube_safe_mode", True)):
        st.info("YouTube Safe Mode is ON. Export is blocked until every selected shot is SAFE.")
    else:
        st.warning("YouTube Safe Mode is OFF. Export will include flagged media and only warn you.")
    st.write(
        "Export creates an **FCPXML timeline**, a **JSON timeline manifest**, "
        "and a **source/license CSV**. Import the FCPXML into DaVinci Resolve; "
        "the clips stay in the same shot order."
    )
    if missing:
        st.warning(
            f"{missing} shots still have no media. They will be omitted "
            "from the exported timeline."
        )
    if selected:
        st.download_button(
            "Download current copyright report",
            data=lf.build_copyright_csv(project).encode("utf-8-sig"),
            file_name=f"{lf.safe_slug(str(project.get('title') or 'longforge'))}-copyright-report.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_live_copyright_report",
        )

    if copyright_summary["issues"]:
        st.markdown("### Copyright review")
        for row in copyright_summary["issues"]:
            label = f"Shot {row['shot']:03d} · {row['status']} · {row['provider']}"
            if row["status"] == lf.YOUTUBE_BLOCK:
                st.error(f"{label}: {row['reason']}")
            else:
                st.warning(f"{label}: {row['reason']}")

    safe_mode_blocked = bool(project.get("youtube_safe_mode", True)) and bool(copyright_summary["issues"])
    if not selected:
        st.info("Select at least one media item before export.")
    elif st.button(
        "Build DaVinci package",
        type="primary",
        use_container_width=True,
        disabled=safe_mode_blocked,
        help=(
            "Resolve the copyright review above or turn off YouTube Safe Mode."
            if safe_mode_blocked
            else None
        ),
    ):
        try:
            st.session_state.lf_last_export = lf.export_project(project)
            st.success("Export package created.")
        except Exception as exc:
            st.error(f"Export failed: {exc}")

    exported = st.session_state.get("lf_last_export")
    if exported:
        download_specs = [
            ("fcpxml", "Download FCPXML", "application/xml"),
            ("manifest", "Download timeline JSON", "application/json"),
            ("credits", "Download source/license CSV", "text/csv"),
            ("copyright", "Download copyright report CSV", "text/csv"),
        ]
        if "narration" in exported:
            download_specs.insert(1, ("narration", "Download narration audio", "audio/mpeg"))
        for key, label, mime in download_specs:
            path = Path(exported[key])
            if path.exists():
                st.download_button(
                    label,
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mime,
                    use_container_width=True,
                    key=f"download_{key}",
                )
        st.caption(
            f"Project folder: {lf.project_dir(str(project['id']))}"
        )
