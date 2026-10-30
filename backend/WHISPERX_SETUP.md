# WhisperX alignment setup

Audio alignment is an optional, CPU-capable extra. The base FastAPI/Gemini
environment remains installable without PyTorch; voice generation now fails
with an explicit alignment error if WhisperX is not installed, rather than
creating estimated captions.

## Windows 11, Python 3.12 (CMD)

From the project root:

```bat
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-alignment.txt
```

Install FFmpeg and FFprobe as documented in the root README, then restart CMD.
The first English, German, and Spanish alignment run downloads the matching
WhisperX alignment model and caches it under the Hugging Face model cache. The
model is reused for later jobs in the same process. This service loads only the
language-specific forced-alignment model and runs it on CPU; Gemini/Edge-TTS
still generates the narration.

## Local verification

```bat
python -m pytest -q
```

An end-to-end voice job additionally needs a valid Gemini API key in
`backend/.env` (or an available Edge-TTS network connection). The voiceover is
passed unchanged to TTS and then to WhisperX as the forced-alignment transcript.
Any incomplete, low-confidence, or mismatched alignment fails the voice job;
there is no estimated-timing fallback.

WhisperX currently declares support for Python 3.10 through 3.13, so the
project's Python 3.12 target is within its published interpreter range. CPU
installation avoids CUDA requirements. See the upstream [WhisperX setup and
CPU usage](https://github.com/m-bain/whisperX#setup-) for platform details.
