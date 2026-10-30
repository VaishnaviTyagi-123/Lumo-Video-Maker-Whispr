"""Streamlit client for the Lumo Living FastAPI backend."""

import json
import os
from urllib.parse import quote

import httpx
import streamlit as st


st.set_page_config(page_title="Lumo Living · Video Studio", page_icon="🌿", layout="wide")


class APIError(Exception):
    """An actionable backend or connection error."""


def request(method, path, *, binary=False, **kwargs):
    try:
        timeout = 1800 if method == "POST" else 30
        response = httpx.request(method, base_url + path, timeout=httpx.Timeout(timeout, connect=10), **kwargs)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except ValueError:
            detail = exc.response.text
        if not isinstance(detail, str):
            detail = json.dumps(detail, indent=2, ensure_ascii=False)
        raise APIError(f"Backend returned {exc.response.status_code}: {detail}") from exc
    except httpx.TimeoutException as exc:
        raise APIError("The backend timed out. Generation may still be running; check the backend before retrying.") from exc
    except httpx.RequestError as exc:
        raise APIError("Cannot reach the backend. Start FastAPI and check the API URL in the sidebar.") from exc
    if binary:
        return response.content
    try:
        return response.json()
    except ValueError as exc:
        raise APIError("The backend returned an unexpected response. Check the API URL.") from exc


@st.cache_data(ttl=300, show_spinner=False)
def media(api_url, path):
    # Include the server in the cache key so switching backends cannot reuse media.
    return request("GET", path, binary=True)


def show_video(result):
    st.success("Your video is ready.")
    st.caption(f"Job ID: {result['job_id']}")
    try:
        video = media(base_url, f"/render/{quote(result['job_id'], safe='')}/video")
        preview, details = st.columns([1, 2])
        with preview:
            st.video(video)
        with details:
            st.download_button("Download MP4", video, file_name=f"lumo-{result['job_id']}.mp4", mime="video/mp4")
            with st.expander("Generation details"):
                st.json(result)
    except APIError as exc:
        st.error(str(exc))


with st.sidebar:
    st.title("🌿 Lumo Living")
    st.caption("AI PRODUCT VIDEO STUDIO")
    base_url = st.text_input("Backend API URL", os.getenv("LUMO_API_URL", "http://127.0.0.1:8000")).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        st.error("Enter an HTTP or HTTPS API URL.")
        st.stop()
    page = st.radio("Workspace", ["Video studio", "Brand guide", "Find a video"])
    if st.button("Refresh backend"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    try:
        health = request("GET", "/health")
        st.success("Backend connected")
        for label, key in [("Gemini API key", "gemini_key_configured"), ("FFmpeg", "ffmpeg_installed"), ("FFprobe", "ffprobe_installed")]:
            st.caption(f"{'✓' if health.get(key) else '○'} {label}")
        st.caption("Voice generation also requires the backend's WhisperX setup.")
    except APIError as exc:
        st.error(str(exc))
        st.code("cd backend\npython -m uvicorn app.main:app --reload")
        st.stop()

st.title("Make room for a little inspiration.")
st.write("Turn your Lumo Living products into narrated, captioned vertical videos.")

try:
    if page == "Brand guide":
        st.subheader("The Lumo Living voice")
        guide = request("GET", "/brand/guide")
        st.markdown(guide["content"])
        with st.expander("Edit brand guide"):
            with st.form("brand_guide"):
                content = st.text_area("Brand guidelines", guide["content"], height=350, max_chars=30000)
                save = st.form_submit_button("Save brand guide")
            if save:
                if not content.strip():
                    st.error("The brand guide cannot be empty.")
                else:
                    request("PUT", "/brand/guide", json={"content": content})
                    st.rerun()
    elif page == "Find a video":
        st.subheader("Open an existing render")
        with st.form("find_job"):
            job_id = st.text_input("Render job ID")
            find = st.form_submit_button("Find video")
        if find and job_id.strip():
            st.session_state.pop("found_video", None)
            st.session_state["found_video"] = (base_url, request("GET", f"/render/{quote(job_id.strip(), safe='')}"))
        found = st.session_state.get("found_video")
        if found and found[0] == base_url:
            if found[1]["status"] == "completed":
                show_video(found[1])
            else:
                st.info(f"Job status: {found[1]['status']}. Use Find video again to refresh.")
    else:
        products = request("GET", "/products")
        languages = request("GET", "/creative/languages")
        voices = request("GET", "/voice/voices")
        if not products or not languages:
            st.info("Add products and configure languages in the backend to get started.")
            st.stop()
        product_column, studio = st.columns([1, 2], gap="large")
        with product_column:
            st.subheader("01 · Choose a product")
            by_id = {item["id"]: item for item in products}
            product_id = st.selectbox("Product", list(by_id), format_func=lambda key: by_id[key]["name"])
            product = by_id[product_id]
            try:
                st.image(media(base_url, f"/products/{quote(product_id, safe='')}/image"), use_container_width=True)
            except APIError:
                st.info("No product image available. Upload one below.")
            st.caption(product["category"])
            st.write(product["description"])
            for feature in product["features"]:
                st.write(f"• {feature}")
            if product.get("sustainability"):
                st.info(product["sustainability"])
            with st.expander("Replace product image"):
                upload = st.file_uploader("PNG or JPEG · up to 8 MB", type=["png", "jpg", "jpeg"], key=f"image-{base_url}-{product_id}")
                if st.button("Upload image", disabled=upload is None):
                    if upload.size > 8 * 1024 * 1024:
                        st.error("Choose an image smaller than 8 MB.")
                    else:
                        request("POST", f"/products/{quote(product_id, safe='')}/images", files={"file": (upload.name, upload.getvalue(), upload.type)})
                        st.cache_data.clear()
                        st.rerun()
        with studio:
            st.subheader("02 · Set the tone")
            left, right = st.columns(2)
            language = left.selectbox("Language", list(languages), format_func=lambda key: languages[key])
            options = voices.get(language, {}).get("gemini", [])
            if not options:
                st.error("No Gemini voices are configured for this language.")
                st.stop()
            voice = right.selectbox("Voice", options, help="The backend may use its Edge TTS fallback when needed.")
            st.caption("15 seconds · 1080 × 1920 · Portrait · Aligned captions")
            context = (base_url, product_id, language, voice)
            if st.session_state.get("studio_context") != context:
                for key in ("creative", "video"):
                    st.session_state.pop(key, None)
                st.session_state["studio_context"] = context
            preview_button, generate_button = st.columns(2)
            preview = preview_button.button("Preview storyboard", use_container_width=True)
            generate = generate_button.button("Generate full video", type="primary", use_container_width=True)
            st.caption("Preview creates a script and storyboard. Full generation runs a fresh creative plan, narration, alignment, and rendering; it can take several minutes.")
            if preview:
                st.session_state.pop("creative", None)
                with st.spinner("Writing and validating your storyboard…"):
                    st.session_state["creative"] = request("POST", "/creative/preview", json={"product_id": product_id, "language": language})
            if generate:
                st.session_state.pop("video", None)
                with st.spinner("Creating your video. Keep this page open…"):
                    st.session_state["video"] = request("POST", "/pipeline/generate", json={"product_id": product_id, "language": language, "voice": voice})
            creative = st.session_state.get("creative")
            if creative:
                st.subheader("Storyboard preview")
                st.write(creative["plan"]["voiceover"])
                for scene in creative["plan"]["scenes"]:
                    with st.container(border=True):
                        st.caption(f"SCENE {scene['index']} · {scene['start_seconds']}–{scene['end_seconds']}s · {scene['animation'].replace('_', ' ')}")
                        st.write(scene["caption"])
                        st.caption(scene["visual_focus"])
                with st.expander("Validation and trace"):
                    st.json(creative)
            if st.session_state.get("video"):
                st.subheader("03 · Your finished video")
                show_video(st.session_state["video"])
except APIError as exc:
    st.error(str(exc))
