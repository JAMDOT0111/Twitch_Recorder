# 🎬 Twitch Auto Recorder

自動偵測 Twitch 實況主開台即時錄影，關台後自動停止。支援多實況主同時追蹤、Docker 部署與本機執行。

---

## 功能亮點

- 自動偵測 Twitch 實況主直播狀態
- 開台時即刻啟動錄影，關台時自動停止
- 支援多實況主同時追蹤
- 自動重啟錄影進程，避免錄影意外終止
- Docker 部署與本機執行皆適用
- 可用環境變數或本機交互式設定
- 可設定錄影畫質與檢查間隔
- 產生 `.ts` 檔案，適用 VLC / mpv 播放

---

## 專案結構

```
twitch-recorder/
├── app/
│   └── twitch_recorder.py   # 主程式
├── recordings/              # 錄影輸出（gitignore）
├── config/                  # 設定檔與日誌（gitignore）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example             # 環境變數範本
├── .env                     # 你的實際設定（gitignore）
└── README.md
```

---

## 快速開始

### 方式一：Docker（推薦）

1. 複製環境變數範本：
```bash
cp .env.example .env
```

2. 編輯 `.env`，填入你的 Twitch API 憑證與追蹤清單：
```env
TWITCH_CLIENT_ID=your_client_id_here
TWITCH_CLIENT_SECRET=your_client_secret_here
TWITCH_STREAMERS=shroud,ninja,pokelawls
QUALITY=best
CHECK_INTERVAL=60
```

3. 啟動服務：
```bash
docker compose up -d
```

4. 查看日誌：
```bash
docker compose logs -f
```

5. 停止服務：
```bash
docker compose down
```

---

### 方式二：本機直接執行

1. 安裝依賴：
```bash
pip install -r requirements.txt
```

2. 進行初始設定：
```bash
python app/twitch_recorder.py setup
```

3. 新增追蹤實況主：
```bash
python app/twitch_recorder.py add shroud
python app/twitch_recorder.py add ninja
```

4. 啟動錄影：
```bash
python app/twitch_recorder.py start
```

---

## CLI 指令

```bash
python app/twitch_recorder.py setup          # 互動式初始設定
python app/twitch_recorder.py start          # 啟動監控並自動錄影
python app/twitch_recorder.py start -v       # 啟動（詳細模式）
python app/twitch_recorder.py add <帳號>     # 新增追蹤
python app/twitch_recorder.py remove <帳號>  # 移除追蹤
python app/twitch_recorder.py list           # 查看追蹤清單
python app/twitch_recorder.py status         # 查看設定
```

Docker 相關：
```bash
docker compose up -d
docker compose logs -f
docker compose down
docker compose restart
```

---

## 參數設定

| 環境變數 | 說明 | 預設值 |
|---|---|---|
| `TWITCH_CLIENT_ID` | Twitch API Client ID | 必填 |
| `TWITCH_CLIENT_SECRET` | Twitch API Client Secret | 必填 |
| `TWITCH_STREAMERS` | 追蹤實況主，逗號分隔 | 必填 |
| `QUALITY` | 錄影畫質 | `best` |
| `CHECK_INTERVAL` | 檢查開台間隔（秒） | `60` |
| `RECORDINGS_DIR` | 錄影輸出路徑（容器內） | `/recordings` |
| `CONFIG_DIR` | 設定檔路徑（容器內） | `/config` |

**畫質選項**（由高到低）：`best` / `1080p60` / `1080p` / `720p60` / `720p` / `480p` / `360p` / `worst`

---

## 運作方式

- 使用 Twitch Helix API 檢查實況主是否開台
- 開台時透過 `streamlink` 開始錄影
- 關台時自動停止錄影程序
- 若錄影程序異常結束，會嘗試重新啟動
- 在 Docker 中，錄影結果會輸出到 `./recordings`，設定檔與日誌保留在 `./config`

---

## 錄影檔說明

- 預設檔名：`{streamer}_{日期}_{時間}.ts`
- 例如：`shroud_20240315_214532.ts`
- `.ts` 可直接用 VLC、mpv 播放

轉成 MP4：
```bash
ffmpeg -i shroud_20240315_214532.ts -c copy shroud_20240315.mp4
```

批次轉換：
```bash
for f in recordings/*.ts; do
  ffmpeg -i "$f" -c copy "${f%.ts}.mp4" && rm "$f"
done
```

---

## 常見問題

**Q: Container 重啟後設定還在嗎？**  
A: 是的，`./config/` 目錄掛載進容器，設定與日誌會保留。

**Q: 網路斷線怎麼辦？**  
A: 程式會在下一次檢查時重新偵測，如果錄影中斷會自動重新啟動。

**Q: Docker 內看得到錄影檔嗎？**  
A: 可以，錄影輸出到宿主機的 `./recordings/`。

**Q: 支援 Apple Silicon（M 系列）嗎？**  
A: 支援，Docker image 使用 `python:3.12-slim`，對 ARM64 相容。

---

## 安全提醒

- ⚠️ `.env` 含有 API 金鑰，**絕對不可 commit 到 Git**
- `.gitignore` 建議排除 `.env`、`recordings/`、`config/`
- 建議在 GitHub Actions 或 CI 使用 `GitHub Secrets` 管理金鑰

---

## 相依套件

```bash
pip install -r requirements.txt
```

---

## 相關檔案

- `app/twitch_recorder.py`：主要程式
- `Dockerfile`：Docker image 建置
- `docker-compose.yml`：容器部署設定
- `.env.example`：環境變數範例
- `requirements.txt`：Python 相依套件
