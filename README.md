# Lumo Living — AI Product Video Maker

**Phase 1 runnable backend** using the provided assignment data. This release does **not** yet generate videos. Phase 2 will add the LangGraph creative director and brand validation; later phases will add Gemini/Edge TTS, FFmpeg rendering, jobs, and MP4 downloads.

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
