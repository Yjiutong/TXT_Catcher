# -*- coding: utf-8 -*-
"""配置管理：默认配置 + 可持久化到 config.json。"""
import json
import os
import sys

if getattr(sys, "frozen", False):  # PyInstaller 打包后
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_NAME = "TXT_Catcher"
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "novel_catcher.db")

DEFAULTS = {
    "output_dir": DEFAULT_OUTPUT_DIR,
    "concurrency": 2,          # 同时下载的书籍数量
    "chapter_pool": 3,         # 单本书内并发抓取章节的线程数
    "timeout": 15,             # 请求超时（秒）
    "retries": 3,              # 请求失败重试次数
    "delay": 0.3,              # 章节请求间隔（秒）
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "max_chapters": 8000,      # 单本书章节数量安全上限
    "max_chapter_pages": 5,    # 单章正文分页最大页数
}


class Config:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k, v in DEFAULTS.items():
                    if k in saved:
                        self.data[k] = saved[k]
        except (OSError, ValueError):
            pass  # 不存在或损坏时使用默认值

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def get(self, key, default=None):
        return self.data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()
