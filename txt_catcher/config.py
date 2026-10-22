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

DEFAULTS = {
    "output_dir": DEFAULT_OUTPUT_DIR,
    "timeout": 15,              # 请求超时（秒）
    "retries": 3,               # 请求失败重试次数
    "delay": 0.3,               # 请求间隔（秒）
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "max_items": 5000,          # 单个合集条目数量安全上限
    "max_item_pages": 10,       # 单个条目正文分页最大页数
    "item_pool": 4,             # 单次集合抓取的并发线程数
    "site_rules": {},           # 站点规则扩展（域名 -> 选择器配置），覆盖/补充内置规则
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
