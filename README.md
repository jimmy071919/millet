# millet

`millet` 是一套本機優先的會議錄音、轉錄、講者分離、中文摘要與 PDF 產出工具。它可以從 Linux 桌面擷取麥克風與系統音訊，使用 WhisperX 轉錄、pyannote 做講者分離，並透過 LM Studio 或其他 OpenAI-compatible API 產生會議摘要。

這個版本預設偏向中文會議工作流：

- 預設語言為中文：`MILLET_LANGUAGE=zh`
- 摘要預設可接 LM Studio local server
- 錄音與所有產出集中在專案內的 `millet-output/`
- 模型與 Hugging Face 快取集中在 `.millet-models/`
- 使用 `.env` 管理 token、模型路徑與 LLM endpoint

## 功能

- 錄製麥克風與系統音訊
- 支援 Zoom、Google Meet、Teams、Discord、Slack、瀏覽器會議等會議來源
- 使用 WhisperX / faster-whisper 進行語音轉文字
- 使用 pyannote 進行 speaker diarization，辨識不同講者
- 預設中文轉錄與中文摘要
- 支援 LM Studio、Ollama、OpenRouter、Claude Max、Tinfoil 等摘要後端
- 產出 `.wav`、`.txt`、`.srt`、`.json`、`.summary.md`、`.pdf`
- 每次會議獨立資料夾管理
- 支援後續講者命名、聲紋註冊與自動標記
- 支援將會議成果同步到 Git repo

## 系統需求

### Linux 桌面完整流程

錄音、轉錄、摘要、PDF 產出都在 Linux 上完成。

建議環境：

- Linux with PipeWire 或 PulseAudio
- Python 3.10+
- `ffmpeg`
- `pulseaudio-utils`，提供 `pactl`
- NVIDIA GPU + CUDA，建議 8GB VRAM 以上
- Hugging Face token，用於 pyannote gated model
- LM Studio，本地 LLM 摘要用

安裝系統套件：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg pulseaudio-utils
```

確認音訊工具可用：

```bash
ffmpeg -version
pactl info
```

### macOS / Windows

- Linux 才支援完整錄音流程。
- macOS 可處理既有音檔，但不支援本專案的桌面系統音訊錄製流程。
- Windows 目前不支援。

## 安裝

### 從 PyPI 安裝

```bash
pip install millet-pipeline
```

### 從原始碼安裝

```bash
git clone <your-repo-url>
cd millet
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

如果已經有 `.venv`，啟動即可：

```bash
source .venv/bin/activate
```

確認 CLI：

```bash
millet --help
```

## 設定

本專案使用 `.env` 管理本機設定。`.env` 不會被提交到 git。

建立設定檔：

```bash
cp .env.example .env
nano .env
```

範例：

```bash
HF_TOKEN=hf_your_token_here

MILLET_MODEL_CACHE_DIR=.millet-models
MILLET_RECORDINGS_DIR=millet-output
MILLET_LANGUAGE=zh

MILLET_SUMMARY_BACKEND=openai
MILLET_OPENAI_BASE_URL=http://localhost:1234/v1
MILLET_SUMMARY_MODEL=your-lm-studio-model-name
MILLET_OPENAI_API_KEY=not-needed
```

### 設定項目

| 變數 | 說明 |
|---|---|
| `HF_TOKEN` | Hugging Face token，用於 pyannote 講者分離 |
| `MILLET_MODEL_CACHE_DIR` | 模型快取資料夾，預設 `.millet-models` |
| `MILLET_RECORDINGS_DIR` | 錄音與輸出資料夾，預設 `millet-output` |
| `MILLET_LANGUAGE` | 預設語言，中文為 `zh`，自動偵測為 `auto` |
| `MILLET_SUMMARY_BACKEND` | 摘要後端，LM Studio 使用 `openai` |
| `MILLET_OPENAI_BASE_URL` | OpenAI-compatible API URL |
| `MILLET_SUMMARY_MODEL` | 摘要模型名稱 |
| `MILLET_OPENAI_API_KEY` | API key；LM Studio 通常可填 `not-needed` |

## Hugging Face token

pyannote 的 speaker diarization model 是 gated model，所以需要 Hugging Face token。

最小權限只需要：

```text
Read access to contents of all public gated repos you can access
```

不需要 write 權限。

建立 token 前，先接受模型條款：

```text
https://huggingface.co/pyannote/speaker-diarization-community-1
```

然後把 token 填到 `.env`：

```bash
HF_TOKEN=hf_xxxxxxxxxxxxxxxxx
```

## LM Studio 設定

1. 開啟 LM Studio
2. 載入模型
3. 開啟 Local Server
4. 確認 API URL，例如：

```text
http://localhost:1234/v1
```

5. 在 `.env` 填入：

```bash
MILLET_SUMMARY_BACKEND=openai
MILLET_OPENAI_BASE_URL=http://localhost:1234/v1
MILLET_SUMMARY_MODEL=your-lm-studio-model-name
MILLET_OPENAI_API_KEY=not-needed
```

模型名稱以 LM Studio server 頁面顯示為準。

## 快速開始

啟動虛擬環境：

```bash
source .venv/bin/activate
```

確認 `millet` 指令位置：

```bash
which millet
```

如果你從原始碼執行，應該指向：

```text
/path/to/millet/.venv/bin/millet
```

確認設定讀取正常：

```bash
python - <<'PY'
from millet.paths import recordings_dir, model_cache_dir, load_project_env, apply_model_cache_environment
from millet.transcribe import TranscriptionConfig

load_project_env()
apply_model_cache_environment()
cfg = TranscriptionConfig(device="cpu", torch_device="cpu")

print("recordings:", recordings_dir())
print("model_cache:", model_cache_dir())
print("language:", cfg.language)
print("hf_token:", bool(cfg.hf_token))
PY
```

預期：

```text
recordings: .../millet-output
model_cache: .../.millet-models
language: zh
hf_token: True
```

開始錄音、轉錄、摘要：

```bash
millet run --compute-type int8 --batch-size 4
```

停止錄音：

```text
Ctrl+C
```

停止後會自動進行：

```text
錄音儲存 → WhisperX 轉錄 → pyannote 講者分離 → LLM 中文摘要 → PDF 產出
```

## 重要確認

開始錄音時應該看到：

```text
Recording to: .../millet-output/meeting-...
Diarize: True
```

如果輸出沒有進入 `millet-output/`，表示目前可能沒有執行到正確的本地環境。請重新啟動 venv 或使用完整路徑：

```bash
./.venv/bin/millet run --compute-type int8 --batch-size 4
```

## 模型下載

第一次執行會下載 Whisper 模型，預設放在：

```text
.millet-models/huggingface/hub/
```

如果處理英文且需要 word-level alignment，可能需要下載英文 alignment model：

```bash
millet download en
```

它會放在：

```text
.millet-models/torch/
```

中文會議通常可以先使用：

```bash
millet run --skip-alignment --compute-type int8 --batch-size 4
```

## 輸出檔案

所有會議輸出預設在：

```text
millet-output/
```

範例：

```text
millet-output/meeting-20260624-165403/
  meeting-20260624-165403.wav
  meeting-20260624-165403.session.json
  meeting-20260624-165403.ffmpeg.log
  meeting-20260624-165403.txt
  meeting-20260624-165403.srt
  meeting-20260624-165403.json
  meeting-20260624-165403.summary.md
  meeting-20260624-165403.summary.meta.json
  meeting-20260624-165403.frontmatter.json
  meeting-20260624-165403.pdf
```

模型與 token 相關快取預設在：

```text
.millet-models/
```

這兩個資料夾都在 `.gitignore` 中。

## 處理既有音檔

轉錄單一音檔：

```bash
millet transcribe path/to/audio.wav --compute-type int8 --batch-size 4
```

指定中文：

```bash
millet transcribe path/to/audio.wav --language zh --compute-type int8 --batch-size 4
```

跳過 alignment：

```bash
millet transcribe path/to/audio.wav --language zh --skip-alignment --compute-type int8 --batch-size 4
```

不做講者分離：

```bash
millet transcribe path/to/audio.wav --no-diarize --compute-type int8 --batch-size 4
```

## 常用命令

列出音訊裝置：

```bash
millet devices
```

檢查基礎環境：

```bash
millet check
```

注意：`millet check` 可能只檢查 shell 內的 `HF_TOKEN`，不一定完整讀取 `.env`。若要確認轉錄流程能讀到 token，請用：

```bash
python - <<'PY'
from millet.transcribe import TranscriptionConfig
cfg = TranscriptionConfig(device="cpu", torch_device="cpu")
print(bool(cfg.hf_token))
PY
```

## 講者標記與聲紋

手動修正講者：

```bash
millet label millet-output/meeting-xxxx
```

建立聲紋：

```bash
millet enroll millet-output/meeting-xxxx
```

之後自動標記：

```bash
millet label --auto millet-output/meeting-xxxx
```

## 語言設定

預設中文：

```bash
MILLET_LANGUAGE=zh
```

臨時改自動偵測：

```bash
millet run --language auto --compute-type int8 --batch-size 4
```

臨時指定英文：

```bash
millet run --language en --compute-type int8 --batch-size 4
```

## 常見問題

### CUDA out of memory

使用 int8 與較小 batch size：

```bash
millet run --compute-type int8 --batch-size 4
```

仍然不足時，改小模型：

```bash
millet run --model medium --compute-type int8 --batch-size 4
millet run --model base --compute-type int8 --batch-size 4
```

### 錄音沒有偵測到人聲

如果看到：

```text
No active speech found in audio
```

可能是錄音太短、麥克風來源錯誤、系統音訊來源錯誤，先檢查：

```bash
millet devices
```

### 產出沒有進入 `millet-output/`

請確認目前執行的是專案環境中的 `millet`：

```bash
which millet
```

從原始碼安裝時，建議啟動 `.venv` 後再執行。也可以直接使用：

```bash
./.venv/bin/millet run --compute-type int8 --batch-size 4
```

### 模型又重新下載

確認模型 cache 是否指到專案內：

```bash
python - <<'PY'
from millet.paths import load_project_env, apply_model_cache_environment
load_project_env(); apply_model_cache_environment()
import os
for key in ["HF_HOME", "HF_HUB_CACHE", "HF_XET_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME"]:
    print(key, os.environ.get(key))
PY
```

應該都指向 `.millet-models/`。

## License

本專案沿用原專案授權，詳見 [LICENSE](LICENSE)。
