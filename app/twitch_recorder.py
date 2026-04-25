#!/usr/bin/env python3
"""
Twitch Auto Recorder
自動偵測實況主開台並錄影，關台時自動停止

支援兩種設定方式：
  1. 環境變數（Docker / CI 推薦）
  2. config.json（本機互動模式）
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import requests

# ──────────────────────────────────────────────
# 路徑：優先用環境變數，方便 Docker 掛載
# ──────────────────────────────────────────────
CONFIG_DIR  = Path(os.environ.get("CONFIG_DIR", str(Path.home() / ".twitch-recorder")))
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE    = CONFIG_DIR / "recorder.log"

DEFAULT_CONFIG = {
    "client_id":      os.environ.get("TWITCH_CLIENT_ID",     ""),
    "client_secret":  os.environ.get("TWITCH_CLIENT_SECRET", ""),
    "streamers":      [s.strip() for s in os.environ.get("TWITCH_STREAMERS", "").split(",") if s.strip()],
    "output_dir":     os.environ.get("RECORDINGS_DIR", str(Path.home() / "Videos" / "TwitchRecordings")),
    "quality":        os.environ.get("QUALITY",        "best"),
    "check_interval": int(os.environ.get("CHECK_INTERVAL", "60")),
    "filename_format": "{streamer}_{date}_{time}.ts",
}

# ──────────────────────────────────────────────
# 日誌
# ──────────────────────────────────────────────
def setup_logging(verbose: bool = False):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 設定管理
# ──────────────────────────────────────────────
def load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # 環境變數優先，未設定才從檔案補充
        if not cfg["client_id"]:     cfg["client_id"]     = saved.get("client_id",     "")
        if not cfg["client_secret"]: cfg["client_secret"] = saved.get("client_secret", "")
        if not cfg["streamers"]:     cfg["streamers"]     = saved.get("streamers",     [])
        for k in ("output_dir", "quality", "check_interval", "filename_format"):
            cfg.setdefault(k, saved.get(k, DEFAULT_CONFIG[k]))
    return cfg

def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ──────────────────────────────────────────────
# Twitch API
# ──────────────────────────────────────────────
class TwitchAPI:
    TOKEN_URL  = "https://id.twitch.tv/oauth2/token"
    STREAM_URL = "https://api.twitch.tv/helix/streams"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id     = client_id
        self.client_secret = client_secret
        self._token:        str | None = None
        self._token_expiry: float      = 0.0
        self._lock         = threading.Lock()

    def _get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            resp = requests.post(self.TOKEN_URL, params={
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "grant_type":    "client_credentials",
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self._token        = data["access_token"]
            self._token_expiry = time.time() + data["expires_in"]
            log.debug("Twitch OAuth token 已更新")
            return self._token

    def is_live(self, username: str) -> tuple[bool, dict]:
        try:
            headers = {
                "Client-ID":     self.client_id,
                "Authorization": f"Bearer {self._get_token()}",
            }
            resp = requests.get(
                self.STREAM_URL,
                headers=headers,
                params={"user_login": username},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return (True, data[0]) if data else (False, {})
        except Exception as e:
            log.warning(f"檢查 {username} 直播狀態失敗：{e}")
            return False, {}

# ──────────────────────────────────────────────
# 錄影工作
# ──────────────────────────────────────────────
class RecordingJob:
    def __init__(self, streamer: str, output_path: Path, quality: str):
        self.streamer    = streamer
        self.output_path = output_path
        self.quality     = quality
        self.process: subprocess.Popen | None = None
        self.started_at  = datetime.now()

    def start(self):
        url = f"https://www.twitch.tv/{self.streamer}"
        cmd = [
            "streamlink",
            "--output",        str(self.output_path),
            "--force",
            "--retry-streams", "5",
            "--retry-max",     "3",
            url,
            self.quality,
        ]
        log.info(f"▶ 開始錄影 {self.streamer}  →  {self.output_path.name}")
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
            duration = datetime.now() - self.started_at
            h, rem   = divmod(int(duration.total_seconds()), 3600)
            m, s     = divmod(rem, 60)
            log.info(f"⏹ 停止錄影 {self.streamer}（時長 {h:02d}:{m:02d}:{s:02d}）")

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

# ──────────────────────────────────────────────
# 主要監控器
# ──────────────────────────────────────────────
class TwitchRecorder:
    def __init__(self, cfg: dict):
        self.cfg   = cfg
        self.api   = TwitchAPI(cfg["client_id"], cfg["client_secret"])
        self.jobs: dict[str, RecordingJob] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def _output_path(self, streamer: str) -> Path:
        out_dir = Path(self.cfg["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        now  = datetime.now()
        name = self.cfg["filename_format"].format(
            streamer=streamer,
            date=now.strftime("%Y%m%d"),
            time=now.strftime("%H%M%S"),
        )
        return out_dir / name

    def _check_streamer(self, username: str):
        live, info = self.api.is_live(username)
        with self._lock:
            if live and username not in self.jobs:
                title = info.get("title", "（無標題）")
                game  = info.get("game_name", "")
                log.info(f"🔴 {username} 開台！《{title}》{'  [' + game + ']' if game else ''}")
                job = RecordingJob(username, self._output_path(username), self.cfg["quality"])
                job.start()
                self.jobs[username] = job

            elif not live and username in self.jobs:
                log.info(f"⚫ {username} 關台")
                job = self.jobs.pop(username)
                threading.Thread(target=job.stop, daemon=True).start()

            elif username in self.jobs and not self.jobs[username].is_running:
                log.warning(f"⚠ {username} 錄影程序意外結束，重新啟動…")
                old = self.jobs.pop(username)
                threading.Thread(target=old.stop, daemon=True).start()
                job = RecordingJob(username, self._output_path(username), self.cfg["quality"])
                job.start()
                self.jobs[username] = job

    def run(self):
        streamers = self.cfg["streamers"]
        if not streamers:
            log.error("未設定任何追蹤實況主！")
            log.error("  本機模式：python twitch_recorder.py add <帳號>")
            log.error("  Docker  ：在 .env 設定 TWITCH_STREAMERS=帳號1,帳號2")
            sys.exit(1)

        log.info("🎬 Twitch 自動錄影啟動")
        log.info(f"   追蹤：{', '.join(streamers)}")
        log.info(f"   輸出：{self.cfg['output_dir']}")
        log.info(f"   間隔：{self.cfg['check_interval']}s  畫質：{self.cfg['quality']}")

        while not self._stop.is_set():
            threads = [threading.Thread(target=self._check_streamer, args=(s,), daemon=True) for s in streamers]
            for t in threads: t.start()
            for t in threads: t.join()
            self._stop.wait(self.cfg["check_interval"])

        for username, job in list(self.jobs.items()):
            log.info(f"程式關閉，停止 {username} 的錄影")
            job.stop()

    def stop(self):
        self._stop.set()

# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def cmd_setup(args, cfg):
    print("\n=== Twitch 自動錄影 — 初始設定 ===\n")
    print("請先至 https://dev.twitch.tv/console 建立應用程式\n")
    cfg["client_id"]     = input(f"Client ID     [{cfg['client_id'] or '未設定'}]: ").strip() or cfg["client_id"]
    cfg["client_secret"] = input(f"Client Secret [{cfg['client_secret'] or '未設定'}]: ").strip() or cfg["client_secret"]
    cfg["output_dir"]    = input(f"錄影輸出資料夾 [{cfg['output_dir']}]: ").strip() or cfg["output_dir"]
    cfg["quality"]       = input(f"錄影畫質 [{cfg['quality']}]: ").strip() or cfg["quality"]
    interval             = input(f"檢查間隔（秒） [{cfg['check_interval']}]: ").strip()
    if interval.isdigit():
        cfg["check_interval"] = int(interval)
    save_config(cfg)
    print("\n✅ 設定已儲存！")

def cmd_add(args, cfg):
    name = args.streamer.lower().strip()
    if name not in cfg["streamers"]:
        cfg["streamers"].append(name)
        save_config(cfg)
        print(f"✅ 已新增追蹤：{name}")
    else:
        print(f"ℹ️  {name} 已在追蹤清單中")

def cmd_remove(args, cfg):
    name = args.streamer.lower().strip()
    if name in cfg["streamers"]:
        cfg["streamers"].remove(name)
        save_config(cfg)
        print(f"✅ 已移除追蹤：{name}")
    else:
        print(f"⚠️  {name} 不在追蹤清單中")

def cmd_list(args, cfg):
    src = " （來自 TWITCH_STREAMERS 環境變數）" if os.environ.get("TWITCH_STREAMERS") else ""
    if not cfg["streamers"]:
        print("目前沒有追蹤任何實況主。")
    else:
        print(f"追蹤清單（{len(cfg['streamers'])} 位）{src}：")
        for s in cfg["streamers"]:
            print(f"  • {s}")

def cmd_status(args, cfg):
    def mask(s): return s[:4] + "****" if len(s) > 4 else "****"
    print("\n=== 目前設定 ===")
    print(f"  Client ID   : {mask(cfg['client_id']) if cfg['client_id'] else '（未設定）'}")
    print(f"  輸出資料夾  : {cfg['output_dir']}")
    print(f"  檢查間隔    : {cfg['check_interval']} 秒")
    print(f"  錄影畫質    : {cfg['quality']}")
    print(f"  追蹤實況主  : {', '.join(cfg['streamers']) or '（無）'}")
    print(f"  設定檔      : {CONFIG_FILE}")
    print(f"  日誌檔      : {LOG_FILE}\n")

def cmd_start(args, cfg):
    if not cfg["client_id"] or not cfg["client_secret"]:
        print("❌ 尚未設定 Twitch API 憑證")
        print("   本機模式：python twitch_recorder.py setup")
        print("   Docker  ：在 .env 填入 TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET")
        sys.exit(1)
    setup_logging(getattr(args, "verbose", False))
    recorder = TwitchRecorder(cfg)

    def _sig(signum, frame):
        log.info("收到結束信號，正在停止…")
        recorder.stop()

    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)
    recorder.run()

# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(prog="twitch-recorder", description="Twitch 自動錄影工具")
    parser.add_argument("-v", "--verbose", action="store_true", help="顯示詳細除錯資訊")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup",  help="互動式初始設定")
    sub.add_parser("start",  help="啟動監控並自動錄影")
    sub.add_parser("list",   help="顯示追蹤清單")
    sub.add_parser("status", help="顯示目前設定")

    p_add = sub.add_parser("add",    help="新增追蹤實況主")
    p_add.add_argument("streamer",   help="Twitch 帳號名稱")
    p_rm  = sub.add_parser("remove", help="移除追蹤實況主")
    p_rm.add_argument("streamer",    help="Twitch 帳號名稱")

    args = parser.parse_args()
    cfg  = load_config()

    {
        "setup":  cmd_setup,
        "add":    cmd_add,
        "remove": cmd_remove,
        "list":   cmd_list,
        "status": cmd_status,
        "start":  cmd_start,
    }.get(args.command, lambda *_: parser.print_help())(args, cfg)

if __name__ == "__main__":
    main()
