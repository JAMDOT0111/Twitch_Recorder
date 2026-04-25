FROM python:3.12-slim

# 安裝 streamlink 依賴與 ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先複製 requirements 利用 Docker layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY app/ .

# 錄影檔輸出目錄（掛載用）
VOLUME ["/recordings"]

# 設定檔目錄（掛載用，方便持久化）
VOLUME ["/config"]

ENV RECORDINGS_DIR=/recordings
ENV CONFIG_DIR=/config

ENTRYPOINT ["python", "twitch_recorder.py"]
CMD ["start"]
