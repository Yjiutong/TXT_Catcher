# -*- coding: utf-8 -*-
"""正文提取与清洗：定位正文容器、清理广告与噪音、识别章节标题与分页。"""
import re
from urllib.parse import urljoin

from .http import Page

# 常见正文容器 id/class 关键词
_CONTENT_KEYWORDS = (
    "chaptercontent", "chapter_content", "chapterContent", "chapter-content",
    "read-content", "readcontent", "read_content", "bookcontent", "book_content",
    "novelcontent", "novel_content", "article", "articlecontent", "article_content",
    "neirong", "content_area", "contentarea", "htmlcontent", "zhengwen",
    "txt", "nr", "text", "main-text", "body", "chapter-body",
)
_CONTENT_PATTERN = re.compile(
    r"(^|[\s_\-:])(" + "|".join(re.escape(k) for k in _CONTENT_KEYWORDS) + r")($|[\s_\-:])",
    re.I,
)

# 明确是噪音的容器关键词（含这些 class 的容器不作为正文候选）
_NOISE_PATTERNS = (
    re.compile(r"(^|[\s_\-])ad($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])ads($|[\s_\-])", re.I),
    re.compile(r"advert", re.I),
    re.compile(r"banner", re.I),
    re.compile(r"(^|[\s_\-])tip($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])menu($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])nav($|[\s_\-])", re.I),
    re.compile(r"footer", re.I),
    re.compile(r"(^|[\s_\-])head($|[\s_\-])", re.I),
    re.compile(r"header", re.I),
    re.compile(r"(^|[\s_\-])foot($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])sidebar($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])rank($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])list($|[\s_\-])", re.I),
    re.compile(r"comment", re.I),
    re.compile(r"recommend", re.I),
    re.compile(r"hot", re.I),
    re.compile(r"(^|[\s_\-])btn($|[\s_\-])", re.I),
    re.compile(r"(^|[\s_\-])tool($|[\s_\-])", re.I),
    re.compile(r"share", re.I),
    re.compile(r"bottom", re.I),
    re.compile(r"topbar", re.I),
    re.compile(r"copyright", re.I),
)

# 单行广告/噪音文本特征（强匹配，命中即剔除该段）
_AD_LINE_PATTERNS = [
    re.compile(r"(天才一秒记住|记住本站|请记住|请收藏|收藏本站|加入书签|加入书架|投推荐票|求推荐票|求月票|订阅支持|打赏|加更|更新通知)"),
    re.compile(r"(手机用户|手机阅读|手机版|wap版|请下载|客户端|APP阅读|下载APP)"),
    re.compile(r"(本章未完|请点击下一页|下章更精彩|请翻页|点击下一页继续)"),
    re.compile(r"(最新网址|最新地址|新网址|新地址|本站网址|本书网址|网址:|地址:|域名|站点|访问方式)"),
    re.compile(r"(笔趣阁|顶点小说|雅文小说|爱阅小说|西红柿小说|追书神器|大书包|新笔下文学|万卷书屋|杰奇|幽幽书屋)", re.I),
    re.compile(r"(返回目录|返回书页|回到顶部|上一章|下一章|回书目|书页目录|章节列表|最新章节)"),
    re.compile(r"(广告|推广|推荐阅读|热门推荐|为您推荐|相关推荐|友情推荐|点击查看)"),
    re.compile(r"(^|\s)(www\.|http)", re.I),
    re.compile(r"^\s*[【\[]?(防盗|防采集|VIP|付费)[】\]]"),
    re.compile(r"(百度|谷歌|搜狗|必应)(搜索|一下)"),
]

_TITLE_SEP_RE = re.compile(r"[\s_\-—|·:：<>《》()（）【】\[\]]+")


def _element_id_class(el) -> str:
    id_ = el.get("id", "") or ""
    cls = " ".join(el.get("class", []) or [])
    return f"{id_} {cls}"


def _looks_like_noise(el) -> bool:
    tag = (el.name or "").lower()
    if tag in ("script", "style", "ins", "iframe", "form", "button", "nav",
               "footer", "aside", "noscript", "svg", "canvas"):
        return True
    idc = _element_id_class(el)
    for p in _NOISE_PATTERNS:
        if p.search(idc):
            return True
    return False


def is_ad_line(text: str) -> bool:
    """判断一行文本是否广告/导航噪音。"""
    if not text:
        return True
    t = text.strip()
    if len(t) < 2:
        return True
    # 短链接行
    for p in _AD_LINE_PATTERNS:
        if p.search(t):
            return True
    return False


def _paragraph_text(p) -> str:
    """提取段落文本并规整空白。"""
    text = p.get_text("", strip=False)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def find_content_container(soup):
    """定位正文容器，返回 BeautifulSoup 元素或 None。

    策略：1) 按 id/class 关键词精确找；2) 启发式段落密度评分。
    """
    if soup is None:
        return None

    # 策略 1：关键词匹配的容器
    candidates = []
    for tag in soup.find_all(["div", "article", "section", "main", "td"]):
        if _looks_like_noise(tag):
            continue
        idc = _element_id_class(tag)
        if _CONTENT_PATTERN.search(idc):
            text = tag.get_text("", strip=True)
            if len(text) >= 100:
                candidates.append(tag)

    if candidates:
        # 取文本最长且段落较多的
        def _score(t):
            ps = t.find_all("p")
            return len(t.get_text("", strip=True)) + 50 * len(ps)
        return max(candidates, key=_score)

    # 策略 2：启发式评分（无关键词命中时）
    best, best_score = None, -1
    for tag in soup.find_all(["div", "article", "section"]):
        if _looks_like_noise(tag):
            continue
        ps = tag.find_all("p")
        if not ps:
            continue
        text = tag.get_text("", strip=True)
        if len(text) < 80:
            continue
        score = len(ps) * 40 + len(text)
        # 子容器中含大量链接说明更像导航，惩罚
        links = tag.find_all("a")
        score -= min(len(links) * 20, 400)
        # 段落占比高加分
        if len(ps) >= 3:
            score += 100
        if score > best_score:
            best, best_score = tag, score
    if best and best_score >= 250:
        return best

    # 策略 2.5：<p> 直接挂在 body 下的页面（如古登堡计划 HTML 版）
    body = soup.body
    if body is not None:
        ps = body.find_all("p")
        long_ps = [p for p in ps if len(p.get_text("", strip=True)) >= 20]
        text = body.get_text("", strip=True)
        if len(ps) >= 3 and len(long_ps) >= 2 and len(text) >= 300:
            return body
    return None


def extract_paragraphs(container) -> list:
    """从正文容器中提取干净段落列表。"""
    if container is None:
        return []

    for tag in container.find_all(["script", "style", "ins", "iframe", "form",
                                   "button", "nav", "footer", "aside", "noscript",
                                   "svg", "canvas", "object", "embed"]):
        tag.decompose()

    # 去掉广告容器
    for tag in list(container.find_all(True)):
        try:
            if _looks_like_noise(tag):
                tag.decompose()
        except Exception:
            pass

    paras = []
    p_tags = container.find_all("p")
    if len(p_tags) >= 2:
        for p in p_tags:
            t = _paragraph_text(p)
            if not t:
                continue
            # 过滤过短或广告行
            if is_ad_line(t):
                continue
            paras.append(t)
    else:
        # 无 <p> 结构：直接按换行切分容器文本
        raw = container.get_text("\n", strip=False)
        for line in re.split(r"\n+", raw):
            line = re.sub(r"[ \t\u3000]+", " ", line).strip()
            if not line or is_ad_line(line):
                continue
            paras.append(line)

    # 去重且保留顺序
    seen, out = set(), []
    for t in paras:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def extract_chapter_title(page: Page, container) -> str:
    """从页面中提取章节标题。"""
    soup = page.soup
    if soup is None:
        return ""
    # 1) 容器内的 h1/h2/h3
    if container is not None:
        for h in container.find_all(["h1", "h2", "h3"], limit=3):
            t = h.get_text("", strip=True)
            if t:
                return t
    # 2) 页面内 h1（正文区之前）
    for h in soup.find_all("h1", limit=5):
        t = h.get_text("", strip=True)
        if t and len(t) <= 60:
            return t
    for h in soup.find_all("h2", limit=5):
        t = h.get_text("", strip=True)
        if t and len(t) <= 60:
            return t
    # 3) <title>
    if soup.title and soup.title.get_text(strip=True):
        t = soup.title.get_text(strip=True)
        # 常见格式：章节名_书名_站名
        parts = [p for p in _TITLE_SEP_RE.split(t) if p]
        if len(parts) >= 2:
            # 章节名通常是第一部分（去掉"章节"标识再判断）
            return parts[0].strip() or parts[-2]
        return t
    return ""


_PAGE_NEXT_RE = re.compile(r"下一页|下页|下一頁|下頁|next page", re.I)
_CHAPTER_NEXT_RE = re.compile(r"下一章|下章|下一節|下一节|next chapter", re.I)


def find_pagination_link(page: Page, container) -> str:
    """在当前页寻找“正文分页”链接（下一页，但排除下一章）。

    判定：链接文本匹配“下一页/下页”；且指向的 URL 与当前 URL 不是不同章节页。
    这里只返回候选链接，由调用方抓取后用标题比对确认。
    """
    soup = page.soup
    if soup is None:
        return ""
    scope = container if container is not None else soup
    for a in scope.find_all("a", href=True):
        text = a.get_text("", strip=True)
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        if _PAGE_NEXT_RE.search(text) and not _CHAPTER_NEXT_RE.search(text):
            abs_url = page.resolve(href)
            if abs_url != page.url:
                return abs_url
    return ""


def find_next_chapter_link(page: Page) -> str:
    """寻找“下一章”链接。"""
    soup = page.soup
    if soup is None:
        return ""
    candidates = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text("", strip=True) + " " + (a.get("title") or "") + " "
                + (a.get("alt") or ""))
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        rel = a.get("rel") or []
        if _CHAPTER_NEXT_RE.search(text) or (isinstance(rel, list) and "next" in rel):
            abs_url = page.resolve(href)
            if abs_url != page.url:
                candidates.append(abs_url)
    if candidates:
        return candidates[0]
    return ""


def find_prev_chapter_link(page: Page) -> str:
    """寻找“上一章”链接。"""
    soup = page.soup
    if soup is None:
        return ""
    for a in soup.find_all("a", href=True):
        text = (a.get_text("", strip=True) + " " + (a.get("title") or "") + " "
                + (a.get("alt") or ""))
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        rel = a.get("rel") or []
        if re.search(r"上一章|上章|上一節|上一节|prev", text, re.I) or (
                isinstance(rel, list) and "prev" in rel):
            abs_url = page.resolve(href)
            if abs_url != page.url:
                return abs_url
    return ""


def looks_like_chapter_page(page: Page) -> bool:
    """判断页面是否像一个章节正文页（用于数字推断验证）。"""
    if page is None or page.soup is None:
        return False
    container = find_content_container(page.soup)
    if container is None:
        return False
    paras = extract_paragraphs(container)
    if len(paras) < 2:
        return False
    total = sum(len(p) for p in paras)
    return total >= 40
