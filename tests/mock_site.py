# -*- coding: utf-8 -*-
"""本地模拟小说站 + 管线端到端测试。

构造三个站点形态，覆盖引擎全部路径：
  BOOK_A  UTF-8 + 目录页 + 广告噪音 + 正文分页
  BOOK_B  GBK 编码 + 零填充数字 URL（无目录 → 数字推断）
  BOOK_C  无数字 URL + 上下章链接（→ 链接行走）
"""
import http.server
import re
import threading
import socketserver
from urllib.parse import unquote

HOST = "127.0.0.1"
PORT = 8765
BASE = f"http://{HOST}:{PORT}"

PARA_POOL = [
    "话说天下大势，分久必合，合久必分。", "只听得一声炮响，四下里喊声大震。",
    "却说此人姓甚名谁，且看下文分解。", "众人闻言，面面相觑，不敢作声。",
    "正是：机关算尽太聪明，反误了卿卿性命。", "次日天明，诸将齐集帐下听令。",
    "这一去，果然凶多吉少，吉少凶多。", "言毕，拂袖而去，头也不回。",
    "忽见山后一支人马，旌旗蔽日而来。", "老将军捋须长叹，感慨万千。",
    "众人齐声喝彩，声震屋瓦。", "暗想：此事若成，天下可图矣。",
    "于是整顿人马，择吉日起程。", "诗曰：滚滚长江东逝水，浪花淘尽英雄。",
    "自此之后，两军相持，各无战事。", "那少年闻言大喜，拜倒在地。",
    "且说城中百姓，闻得大军将至，纷纷收拾细软。", "帐外风雪交加，寒气逼人。",
]


def _paras(n: int = 8):
    out = []
    for i in range(n):
        out.append(f"<p>{PARA_POOL[(i * 7 + 3) % len(PARA_POOL)]}</p>")
    return "".join(out)


def _ad_block():
    return ('<div class="ad"><p>广告：请下载XX小说APP，海量好书免费看</p></div>'
            '<p>天才一秒记住本站地址：www.example.com，最快更新无弹窗！</p>'
            '<div class="footer">版权所有 测试站</div>')


def _page(title, body, encoding="utf-8", extra_head=""):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="{encoding}"><title>{title}_测试小说_模拟站</title>{extra_head}</head>
<body>
<div id="header"><a href="/">首页</a> | <a href="/">小说分类</a></div>
<div class="chaptercontent" id="content">{_ad_block()}{body}</div>
</body></html>"""
    return html.encode(encoding)


def _toc_page(links):
    lis = "".join(f'<li><a href="{u}">{t}</a></li>' for t, u in links)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>测试小说_目录</title></head>
<body>
<h1>测试小说</h1>
<div class="chapterlist" id="list">
<ul>{lis}</ul>
</div>
</body></html>"""
    return html.encode("utf-8")


def _a_links():
    titles = [f"第{i:02d}章·测试回目{chr(64 + i)}" for i in range(1, 13)]
    links = []
    for i, t in enumerate(titles, 1):
        if i == 3:
            # 第3章带分页
            links.append((t, f"/ba/3.html"))
        else:
            links.append((t, f"/ba/{i}.html"))
    return links


def _a_chapter(n: int):
    title = f"第{n:02d}章·测试回目{chr(64 + n)}"
    body = _paras(8)
    nav = ""
    if n > 1:
        prev = "/ba/3.html" if n == 4 else f"/ba/{n - 1}.html"
        nav += f'<a href="{prev}">上一章</a> '
    if n < 12:
        nxt = "/ba/4.html" if n == 3 else f"/ba/{n + 1}.html"
        nav += f'<a href="{nxt}">下一章</a> '
    nav += '<a href="/ba/index.html">目录</a>'
    if n == 3:
        nav += ' <a href="/ba/3_2.html">下一页</a>'
    return _page(title, f"<h1>{title}</h1>{body}<div class='nav'>{nav}</div>")


def _b_chapter(n: int):
    title = f"第{n:03d}回·测试正文"
    body = _paras(6)
    return _page(title, f"<h1>{title}</h1>{body}", encoding="gbk")


def _c_page(n: int):
    name = ["chapter-one", "chapter-two", "chapter-three", "chapter-four",
            "chapter-five", "chapter-six"][n - 1]
    title = f"Chapter {n}: Test Story"
    nav = ""
    if n > 1:
        nav += f'<a href="/bc/{["chapter-one","chapter-two","chapter-three","chapter-four","chapter-five"][n-2]}.html">上一章</a> '
    if n < 6:
        nav += f'<a href="/bc/{["chapter-two","chapter-three","chapter-four","chapter-five","chapter-six"][n-1]}.html">下一章</a> '
    body = _paras(6)
    return _page(title, f"<h1>{title}</h1>{body}<div>{nav}</div>")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/ba/index.html":
            data = _toc_page(_a_links())
        elif re.fullmatch(r"/ba/(\d+)\.html", path):
            n = int(re.fullmatch(r"/ba/(\d+)\.html", path).group(1))
            if 1 <= n <= 12:
                data = _a_chapter(n)
            else:
                self.send_error(404)
                return
        elif path == "/ba/3_2.html":
            # 分页第2页：使用与第1页不同的段落
            p2 = ("<p>话说天下大势，分久必合，合久必分。</p>"
                  "<p>那少年闻言大喜，拜倒在地。</p>"
                  "<p>正是：机关算尽太聪明，反误了卿卿性命。</p>"
                  "<p>自此之后，两军相持，各无战事。</p>"
                  "<p>帐外风雪交加，寒气逼人。</p>")
            data = _page("第03章·测试回目C",
                         f"<h1>第03章·测试回目C</h1>{p2}<div class='nav'><a href='/ba/4.html'>下一章</a></div>")
        elif re.fullmatch(r"/bb/第(\d+)章\.html", path):
            n = int(re.fullmatch(r"/bb/第(\d+)章\.html", path).group(1))
            if 1 <= n <= 8:
                data = _b_chapter(n)
            else:
                self.send_error(404)
                return
        elif re.fullmatch(r"/bc/[\w-]+\.html", path):
            names = ["chapter-one", "chapter-two", "chapter-three", "chapter-four",
                     "chapter-five", "chapter-six"]
            if path.split("/")[-1] in [f"{x}.html" for x in names]:
                n = names.index(path.split("/")[-1][:-5]) + 1
                data = _c_page(n)
            else:
                self.send_error(404)
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        # 不声明 charset，让客户端走 HTML meta / 内容探测路径（更贴近部分真实站）
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class MockSite:
    """启动/停止本地模拟站。"""

    def __init__(self, port: int = PORT):
        self.port = port
        self._server = None
        self._thread = None

    def start(self):
        self._server = socketserver.TCPServer((HOST, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
