# millet 中文會議錄音轉錄工具

這個 repo 是 `millet-pipeline` 的本地化版本，目標是把會議錄音、轉錄、講者分離、中文摘要與 PDF 產出集中在同一個專案資料夾內管理。

目前預設行為：

- 會議語言預設為中文：`MILLET_LANGUAGE=zh`
- LLM 摘要走 LM Studio 的 OpenAI-compatible API
- 錄音、轉錄、摘要、PDF 只放在 `millet-output/`
- Hugging Face / Whisper / transformers / torch 快取只放在 `.millet-models/`
- `.env` 管理 token、LM Studio URL、模型名稱與路徑
- `.env`、`.millet-models/`、`millet-output/` 都不會被 git commit

## 目錄

- [整體流程](#整體流程)
- [第一次設定](#第一次設定)
- [設定 .env](#設定-env)
- [啟動 LM Studio](#啟動-lm-studio)
- [確認 millet 指令使用正確版本](#確認-millet-指令使用正確版本)
- [下載必要模型](#下載必要模型)
- [開始錄音與轉錄](#開始錄音與轉錄)
- [處理既有錄音](#處理既有錄音)
- [輸出檔案位置](#輸出檔案位置)
- [常用命令](#常用命令)
- [講者標記與聲紋](#講者標記與聲紋)
- [排錯](#排錯)
- [Git 操作](#git-操作)

## 整體流程

```text
啟動 venv
→ 檢查 .env
→ 啟動 LM Studio server
→ 確認音訊工具 pactl / ffmpeg 可用
→ millet run 開始錄音
→ Ctrl+C 停止錄音
→ WhisperX 轉錄
→ pyannote 講者分離
→ LM Studio 產生中文摘要
→ 產出 txt / srt / json / summary.md / pdf
```

## 第一次設定

進入專案：

```bash
cd /mnt/5be038a8-6538-4ad0-a911-de8b54d7325c/6_code/self/millet
```

啟動虛擬環境：

```bash
source .venv/bin/activate
```

安裝系統音訊工具：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg pulseaudio-utils
```

確認音訊工具可用：

```bash
ffmpeg -version
pactl info
```

## 設定 .env

複製範本：

```bash
cp .env.example .env
nano .env
```

`.env` 內容範例：

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

欄位說明：

| 變數 | 用途 |
|---|---|
| `HF_TOKEN` | Hugging Face token，用於 pyannote 講者分離模型 |
| `MILLET_MODEL_CACHE_DIR` | 模型快取資料夾，預設 `.millet-models` |
| `MILLET_RECORDINGS_DIR` | 所有輸出資料夾，預設 `millet-output` |
| `MILLET_LANGUAGE` | 預設語言，中文使用 `zh` |
| `MILLET_SUMMARY_BACKEND` | 摘要後端，LM Studio 使用 `openai` |
| `MILLET_OPENAI_BASE_URL` | LM Studio server URL，通常是 `http://localhost:1234/v1` |
| `MILLET_SUMMARY_MODEL` | LM Studio 中載入的模型名稱 |
| `MILLET_OPENAI_API_KEY` | LM Studio 通常填 `not-needed` |

`.env` 已被 `.gitignore` 排除，不會被提交。

### Hugging Face token 權限

Hugging Face token 最小權限只需要：

```text
Read access to contents of all public gated repos you can access
```

不需要 write 權限。

還要先到模型頁面接受條款：

```text
https://huggingface.co/pyannote/speaker-diarization-community-1
```

## 啟動 LM Studio

在 LM Studio：

1. 載入你要用的模型
2. 開啟 Local Server
3. 確認 API URL 是：

```text
http://localhost:1234/v1
```

4. 把模型名稱填進 `.env`：

```bash
MILLET_SUMMARY_MODEL=gpt-oss-20b
```

實際名稱以 LM Studio server 頁面顯示為準。

## 確認 millet 指令使用正確版本

每次開新 terminal 後：

```bash
cd /mnt/5be038a8-6538-4ad0-a911-de8b54d7325c/6_code/self/millet
source .venv/bin/activate
export PATH="$PWD/.venv/bin:$PATH"
hash -r
which millet
```

`which millet` 必須顯示：

```text
/mnt/5be038a8-6538-4ad0-a911-de8b54d7325c/6_code/self/millet/.venv/bin/millet
```

確認設定有被讀到：

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

預期輸出：

```text
recordings: .../millet/millet-output
model_cache: .../millet/.millet-models
language: zh
hf_token: True
```

## 下載必要模型

### Whisper 轉錄模型

第一次執行 `millet run` 或 `millet transcribe` 會自動下載 Whisper 模型。模型會放在：

```text
.millet-models/huggingface/hub/
```

### 英文 alignment 模型

如果處理英文會議，可能需要下載英文 alignment model：

```bash
millet download en
```

這會下載約 360MB，放到：

```text
.millet-models/torch/
```

### 中文會議建議

中文預設是：

```bash
MILLET_LANGUAGE=zh
```

中文 alignment 在目前專案沒有預先註冊。如果 alignment 出問題，可以加：

```bash
--skip-alignment
```

例如：

```bash
millet run --skip-alignment --compute-type int8 --batch-size 4
```

## 開始錄音與轉錄

推薦指令：

```bash
millet run --compute-type int8 --batch-size 4
```

看到這兩行才是正確狀態：

```text
Recording to: .../millet/millet-output/meeting-...
Diarize: True
```

停止錄音：

```text
Ctrl+C
```

停止後會自動進行：

```text
轉錄 → 講者分離 → 中文摘要 → PDF
```

如果 GPU VRAM 不夠，改用較小模型：

```bash
millet run --model medium --compute-type int8 --batch-size 4
```

更保守：

```bash
millet run --model base --compute-type int8 --batch-size 4
```

## 處理既有錄音

處理單一音檔：

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

## 輸出檔案位置

所有產出應該只在：

```text
millet-output/
```

每次會議會建立一個資料夾：

```text
millet-output/meeting-20260624-165403/
```

常見檔案：

```text
meeting-20260624-165403.wav                 # 錄音檔
meeting-20260624-165403.session.json        # 錄音 metadata
meeting-20260624-165403.ffmpeg.log          # ffmpeg log
meeting-20260624-165403.txt                 # 純文字轉錄
meeting-20260624-165403.srt                 # 字幕檔
meeting-20260624-165403.json                # 完整轉錄資料
meeting-20260624-165403.summary.md          # 中文摘要
meeting-20260624-165403.summary.meta.json   # 摘要 metadata
meeting-20260624-165403.frontmatter.json    # 結構化 metadata
meeting-20260624-165403.pdf                 # PDF 報告
```

模型快取只應該在：

```text
.millet-models/
```

檢查是否有外部殘留：

```bash
du -sh /home/jimmy/meet-recordings /home/jimmy/.cache/huggingface /home/jimmy/.cache/torch 2>/dev/null || true
```

正常情況不應該有大型檔案。

## 常用命令

確認音訊裝置：

```bash
millet devices
```

檢查基本環境：

```bash
millet check
```

注意：`millet check` 來自底層 `millet-record`，可能不完整讀取 `.env`，所以即使它顯示 `HF_TOKEN: NOT SET`，只要下面這個檢查是 `True` 就可以：

```bash
python - <<'PY'
from millet.transcribe import TranscriptionConfig
cfg = TranscriptionConfig(device="cpu", torch_device="cpu")
print(bool(cfg.hf_token))
PY
```

開始錄音：

```bash
millet run --compute-type int8 --batch-size 4
```

指定自動偵測語言：

```bash
millet run --language auto --compute-type int8 --batch-size 4
```

指定英文：

```bash
millet run --language en --compute-type int8 --batch-size 4
```

指定中文：

```bash
millet run --language zh --compute-type int8 --batch-size 4
```

## 講者標記與聲紋

轉錄完成後，如果講者名稱不準，可以手動標記：

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

## 排錯

### 存到 `/home/jimmy/meet-recordings`

代表你沒有跑到專案內的 `.venv/bin/millet`。

修正：

```bash
cd /mnt/5be038a8-6538-4ad0-a911-de8b54d7325c/6_code/self/millet
source .venv/bin/activate
export PATH="$PWD/.venv/bin:$PATH"
hash -r
which millet
```

`which millet` 必須是：

```text
.../self/millet/.venv/bin/millet
```

### 又重新下載 1.62GB 模型

代表 Hugging Face cache 沒有指到 `.millet-models`。

確認：

```bash
python - <<'PY'
from millet.paths import load_project_env, apply_model_cache_environment
load_project_env(); apply_model_cache_environment()
import os
for k in ["HF_HOME", "HF_HUB_CACHE", "HF_XET_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME"]:
    print(k, os.environ.get(k))
PY
```

都應該指到本專案底下。

### `CUDA failed with error out of memory`

降低 batch size 並使用 int8：

```bash
millet run --compute-type int8 --batch-size 4
```

還是不行就換小模型：

```bash
millet run --model medium --compute-type int8 --batch-size 4
millet run --model base --compute-type int8 --batch-size 4
```

### `Alignment model for English is not downloaded`

下載英文 alignment：

```bash
millet download en
```

或跳過 alignment：

```bash
millet run --skip-alignment --compute-type int8 --batch-size 4
```

### `No active speech found in audio`

通常代表測試錄音太短、沒有人聲、麥克風/系統聲音來源不對。先確認裝置：

```bash
millet devices
```

## Git 操作

目前 remote：

```text
origin   https://github.com/jimmy071919/millet.git
upstream https://github.com/pretyflaco/millet.git
```

日常修改後：

```bash
git status
git add .
git commit -m "描述這次修改"
git push
```

從原作者同步更新：

```bash
git fetch upstream
git merge upstream/main
```

## 授權

原專案使用 GPL-3.0，詳見 [LICENSE](LICENSE)。
