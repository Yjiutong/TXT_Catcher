# -*- coding: utf-8 -*-
"""通用工具函数。"""
import re
import time
import threading

_URL_NUM_RE = re.compile(r"(?<!\d)(\d+)(?!\d)")


def normalize_url(url: str) -> str:
    """规范化 URL：去空白、去锚点、保留查询串。"""
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    # 去掉 # 锚点
    if "#" in url:
        url = url.split("#", 1)[0]
    return url


def is_same_host(url_a: str, url_b: str) -> bool:
    """判断两个 URL 是否同源（主机部分相同）。"""
    import urllib.parse
    try:
        ha = urllib.parse.urlparse(url_a).netloc.lower()
        hb = urllib.parse.urlparse(url_b).netloc.lower()
        return ha == hb
    except Exception:
        return False


def extract_url_number(url: str):
    """提取 URL 中最后一个数字段；无数字返回 None。"""
    import urllib.parse
    path = urllib.parse.urlparse(url).path
    nums = _URL_NUM_RE.findall(path)
    if not nums:
        return None
    return int(nums[-1])


def replace_last_number(url: str, new_num) -> str:
    """把 URL 路径中最后一个数字替换为新数字（保留原有零填充宽度）。

    例：/book/第001回 -> new_num=2 时得到 /book/第002回。
    """
    import urllib.parse
    parts = urllib.parse.urlparse(url)
    path = parts.path
    # 只替换路径中最后一处数字
    matches = list(_URL_NUM_RE.finditer(path))
    if not matches:
        return url
    m = matches[-1]
    width = m.end() - m.start()
    s = str(new_num)
    if len(s) < width:
        s = s.zfill(width)
    new_path = path[: m.start()] + s + path[m.end():]
    return urllib.parse.urlunparse(
        (parts.scheme, parts.netloc, new_path, parts.params, parts.query, parts.fragment))


def safe_filename(name: str, fallback: str = "未命名") -> str:
    """把标题/条目名转成安全的文件名。"""
    if not name:
        return fallback
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", name).strip()
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    return name[:120] or fallback


def text_word_count(text: str) -> int:
    """统计字数：去掉所有空白字符后的字符数。"""
    return len(re.sub(r"\s", "", text))


def dedupe_keep_order(items, key=None):
    """保持顺序去重。"""
    seen = set()
    out = []
    for it in items:
        k = key(it) if key else it
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


class RateLimiter:
    """简单的线程安全限速器：保证任意两次请求间隔 >= delay 秒。"""

    def __init__(self, delay: float = 0.3):
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            wait = self.delay - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


def format_size(n_bytes: int) -> str:
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.1f} KB"
    return f"{n_bytes / (1024 * 1024):.2f} MB"


def format_word_count(n: int) -> str:
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return f"{n}"
