# -*- coding: utf-8 -*-
"""HTTP 抓取层：浏览器 TLS 指纹模拟、会话管理、重试、编码识别、限速。

优先使用 curl_cffi（impersonate 浏览器指纹，可突破常见 TLS 反爬），
不可用时自动回退到 requests。
"""
import threading
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import charset_normalizer

from .. import utils
from ..config import Config

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL = True
except Exception:
    curl_requests = None
    HAS_CURL = False

try:
    import requests as std_requests
    HAS_REQUESTS = True
except Exception:
    std_requests = None
    HAS_REQUESTS = False

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

IMPRESONATE = ["chrome131", "chrome124", "chrome120", "safari170"]


class FetchError(Exception):
    """抓取失败（网络错误 / HTTP 错误 / 解码失败）。"""


class Page:
    """一个已抓取的页面。"""

    def __init__(self, url: str, final_url: str, status_code: int, html: str, soup):
        self.url = url
        self.final_url = final_url
        self.status_code = status_code
        self.html = html
        self.soup = soup

    def resolve(self, href: str) -> str:
        return urljoin(self.final_url or self.url, href)


class HttpFetcher:
    def __init__(self, config: Config, logger=None):
        self.config = config
        self.logger = logger
        self.limiter = utils.RateLimiter(config.get("delay", 0.3))
        self._ua_index = 0
        self._imp_index = 0
        self._local = threading.local()
        self._backend = "curl" if HAS_CURL else ("requests" if HAS_REQUESTS else None)

    def _log(self, msg: str):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass

    def _next_ua(self) -> str:
        self._ua_index = (self._ua_index + 1) % len(UA_LIST)
        return self.config.get("user_agent") or UA_LIST[self._ua_index]

    def _next_imp(self) -> str:
        self._imp_index = (self._imp_index + 1) % len(IMPRESONATE)
        return IMPRESONATE[self._imp_index]

    def _session(self):
        """每个线程独立的会话对象（会话非线程安全）。"""
        if not hasattr(self._local, "session"):
            if self._backend == "curl":
                self._local.session = curl_requests.Session(
                    impersonate=self._next_imp())
            else:
                s = std_requests.Session()
                s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
                self._local.session = s
        return self._local.session

    def fetch(self, url: str, referer: str = None) -> Page:
        """抓取一个页面，自动处理重试与编码。"""
        url = utils.normalize_url(url)
        if not url.startswith(("http://", "https://")):
            raise FetchError(f"无效的 URL：{url}")

        timeout = self.config.get("timeout", 15)
        retries = self.config.get("retries", 3)
        last_err = None
        for attempt in range(retries + 1):
            self.limiter.wait()
            headers = {
                "User-Agent": self._next_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            if referer:
                headers["Referer"] = referer
            try:
                session = self._session()
                if self._backend == "curl":
                    resp = session.get(url, headers=headers, timeout=timeout,
                                       allow_redirects=True)
                else:
                    resp = session.get(url, headers=headers, timeout=timeout,
                                       allow_redirects=True)
                if resp.status_code in (404, 410):
                    raise FetchError(f"页面不存在（HTTP {resp.status_code}）：{url}")
                if resp.status_code == 403:
                    raise FetchError(f"被拒绝访问（HTTP 403）：{url}（站点可能有反爬限制）")
                resp.raise_for_status()
                html = self._decode(resp)
                soup = BeautifulSoup(html, "lxml")
                return Page(url, resp.url, resp.status_code, html, soup)
            except FetchError:
                raise
            except Exception as e:
                last_err = e
                self._log(f"[http] 请求失败 {url}：{e}（第 {attempt + 1} 次）")
                # 连接被重置等瞬时错误：换指纹重试
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    if self._backend == "curl":
                        try:
                            self._local.session.close()
                        except Exception:
                            pass
                        self._local.session = curl_requests.Session(
                            impersonate=self._next_imp())
        raise FetchError(f"请求失败（已重试 {retries} 次）：{url}：{last_err}")

    def head_ok(self, url: str) -> bool:
        """轻量探测 URL 是否可访问。"""
        url = utils.normalize_url(url)
        try:
            self.limiter.wait()
            session = self._session()
            resp = session.head(
                url, headers={"User-Agent": self._next_ua(),
                              "Accept": "text/html,*/*;q=0.8"},
                timeout=min(self.config.get("timeout", 15), 8), allow_redirects=True)
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _decode(resp) -> str:
        """按优先级识别编码：响应头 charset -> HTML meta -> 内容探测 -> 兜底。"""
        content = resp.content
        if not content:
            return ""
        # 1) 响应头 charset
        ct = resp.headers.get("Content-Type", "")
        if "charset=" in ct.lower():
            enc = ct.lower().split("charset=", 1)[1].split(";")[0].strip().strip("\"'")
            try:
                return content.decode(enc, errors="replace")
            except LookupError:
                pass
        # 2) HTML meta charset（前 4096 字节内找）
        import re
        m = re.search(rb'charset=["\']?([\w-]+)', content[:4096])
        if m:
            meta = m.group(1).decode("ascii", "ignore")
            try:
                return content.decode(meta, errors="replace")
            except LookupError:
                pass
        # 3) 内容统计探测
        try:
            best = charset_normalizer.from_bytes(content).best()
            if best and best.encoding and best.encoding.lower() not in ("ascii",):
                return str(best)
        except Exception:
            pass
        # 4) 常见中文站编码兜底
        for enc in ("utf-8", "gb18030", "gbk"):
            try:
                return content.decode(enc)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")
