# Lumo Living — AI Product Video Maker

FastAPI backend and Streamlit frontend for product storyboards, brand validation, narrated video generation, and MP4 downloads.

## Streamlit frontend

Start the backend from `backend` with its dependencies installed and virtual environment activated:

```bat
python -m uvicorn app.main:app --reload
```

In a second terminal, from the project root, install and start the frontend (it can use a separate virtual environment):

```bat
python -m pip install -r frontend/requirements.txt
python -m streamlit run frontend/app.py
```

Open http://localhost:8501. The sidebar connects to `http://127.0.0.1:8000` by default; change it there or set `LUMO_API_URL` before starting Streamlit. Requests and media downloads run through the Streamlit server, so the API URL must be reachable from that server.

Choose a product, language, and voice to preview a storyboard or generate a complete video. Full generation creates a fresh plan independently of the preview and can take several minutes. Completed videos can be played and downloaded; save the displayed job ID to reopen a render using **Find a video**. The studio also supports replacing product images and viewing/editing the brand guide.

Video generation requires the backend Gemini credentials, FFmpeg/FFprobe, and the [WhisperX setup](backend/WHISPERX_SETUP.md). The frontend alone does not install these dependencies. Backend errors and brand-validation failures appear in the UI. Generation requests are synchronous with a 30-minute client timeout; a timeout does not cancel work on the backend.

## Windows 11 CMD setup

1. Install Python 3.11 or 3.12 (recommended). Check: `py -0p`.
2. Install FFmpeg with `winget install --id Gyan.FFmpeg -e` (or download from https://ffmpeg.org/download.html), then **open a new CMD** and check `ffmpeg -version` and `ffprobe -version`. FFmpeg is not required to run Phase 1.
3. Open CMD in the extracted project folder:

```bat
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
notepad .env
uvicorn app.main:app --reload
```

If you have Python 3.11 instead, replace `py -3.12` with `py -3.11`. Add your Gemini API key only in `.env`, not in source code. If you leave the key blank, all Phase 1 catalog and brand APIs still work.

Open http://127.0.0.1:8000/docs for Swagger UI.

### Swagger walkthrough

1. `GET /health` — check environment readiness.
2. `GET /products` — five seeded products.
3. `GET /products/LL-003` — inspect the diffuser.
4. `GET /products/LL-003/image` — view/download its image.
5. `GET /brand/guide` — inspect the actual assignment rules.
6. `GET /video-spec` — exactly 15 seconds, 1080×1920.
7. `GET /gemini/models` — optional live API-key/model access check; returns 400 if no key is configured.

### Run tests

Stop the server or open a second CMD in `backend` with the virtual environment activated:

```bat
python -m pytest -q
```

### WhisperX word alignment

Caption timing uses forced alignment against the generated narration. Install
the optional WhisperX CPU extra before generating voice jobs; setup steps for
Windows/Python 3.12 are in [backend/WHISPERX_SETUP.md](backend/WHISPERX_SETUP.md).
Alignment errors stop voice generation instead of silently reverting to
estimated caption times.

### Data layout

`backend/data/products.json` contains the five provided products. `backend/data/images/LL-001.png` through `LL-005.png` are the supplied illustrations. `backend/data/brand-guide.md` is the provided policy. On first launch, SQLite is created at `backend/data/app.db` and missing products are seeded without overwriting existing records.

### Constraints and security

Local development only: no authentication is configured. Do not expose these write endpoints to the public internet. Uploaded product images are verified by Pillow and capped at 8 MB. Brand guide updates write to the local Markdown file; do not use the update endpoint if you want to preserve the original verbatim. The Phase 1 `/gemini/models` endpoint is an access check, not proof that every model supports your intended TTS features. The future rendering pipeline must verify exact 15-second duration with FFprobe.
