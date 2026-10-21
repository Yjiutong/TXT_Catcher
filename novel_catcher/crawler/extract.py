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

# 章节标题常见前缀噪音（novel_spider 用 lstrip('章 节目录 ') 处理同类问题）
_TITLE_PREFIXES = ("章 节目录", "章节目录", "正文", "最新章节", "章节")

# 规则提取的正文质量门槛（低于此视为规则失效，回退启发式）
_RULE_MIN_PARAS = 1
_RULE_MIN_TEXT = 40

# 书名 / 作者元信息常见 id/class 关键词
_BOOK_TITLE_IDCLASS_RE = re.compile(
    r"(bookname|book-name|book_name|book-title|book_title|book_info|bookinfo|"
    r"book-info|book_mulu|bookmulu|novelname|novel-name|novel_name|novel-title|"
    r"book_header|bookHeader|book-head|bookhead|book-detail|bookdetail|title-panel)",
    re.I,
)
_AUTHOR_IDCLASS_RE = re.compile(
    r"(author|writer|zuozhe|book-author|bookauthor|author-name|author_name|"
    r"creator|create-user)",
    re.I,
)
_BOOK_TITLE_PREFIX_RE = re.compile(r"^\s*(书名|作品名|小说名|书籍名|书名：|作品名：|小说名：|书籍名：)[:：]?\s*", re.I)
_TITLE_SUFFIX_RE = re.compile(r"(目录|章节目录|章节列表|最新章节|小说阅读|阅读网|笔趣阁|顶点小说)$", re.I)


def clean_title(title: str, rule=None) -> str:
    """清洗章节标题：去掉站点前缀噪音与空白。"""
    if not title:
        return ""
    t = title.strip()
    if rule:
        strip = (rule.get("title_strip") or "").strip()
        if strip and t.startswith(strip):
            t = t[len(strip):].lstrip()
    for p in _TITLE_PREFIXES:
        if t.startswith(p):
            t = t[len(p):].lstrip(" ：: ")
            break
    return t.strip()


def extract_title_by_rule(soup, rule) -> str:
    """按规则的 title 选择器提取章节标题。"""
    if soup is None or not (rule or {}).get("title"):
        return ""
    try:
        el = soup.select_one(rule["title"])
    except Exception:
        return ""
    if el is None:
        return ""
    return clean_title(el.get_text("", strip=True), rule)


def extract_chapter_by_rule(soup, rule):
    """按规则的 content 选择器定位正文容器；质量不合格返回 None（回退启发式）。

    注意：只做轻量校验、不分解噪音节点，避免破坏"先找分页链接再清洗正文"的顺序。
    """
    if soup is None or not (rule or {}).get("content"):
        return None
    try:
        el = soup.select_one(rule["content"])
    except Exception:
        return None
    if el is None or _looks_like_noise(el):
        return None
    text = el.get_text("", strip=True)
    if len(text) < _RULE_MIN_TEXT:
        return None
    # 至少要有真实正文结构（若干段落或较长连续文本）
    if len(el.find_all("p")) < _RULE_MIN_PARAS and len(text) < 120:
        return None
    return el


def find_next_chapter_link_by_rule(page: Page, rule) -> str:
    """按规则的 next 选择器找“下一章”链接。"""
    if page is None or page.soup is None or not (rule or {}).get("next"):
        return ""
    try:
        el = page.soup.select_one(rule["next"])
    except Exception:
        return ""
    if el is None:
        return ""
    href = (el.get("href") or "").strip()
    if not href or href.startswith(("javascript:", "#")):
        return ""
    abs_url = page.resolve(href)
    return abs_url if abs_url != page.url else ""


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
        # 无 <p> 结构：支持 <br> 与块级标签分隔（NovelGetter 的 nodesToText 思路）
        lines = []

        def _walk(node):
            for child in getattr(node, "children", []):
                if getattr(child, "name", None) is None:
                    text = str(child).replace("\xa0", " ").replace("\u3000", " ")
                    if text:
                        lines.append(text)
                    continue
                if child.name == "br":
                    lines.append("\n")
                    continue
                if child.name in ("p", "div", "section", "article", "h1", "h2",
                                  "h3", "h4", "li", "blockquote"):
                    _walk(child)
                    lines.append("\n")
                    continue
                _walk(child)

        _walk(container)
        for line in re.split(r"\n+", "".join(lines)):
            line = re.sub(r"[ \t\u3000\xa0]+", " ", line).strip()
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
            return clean_title(parts[0].strip() or parts[-2])
        return clean_title(t)
    return ""


def _normal_text(text: str) -> str:
    """规整文本用于书名/作者匹配。"""
    if not text:
        return ""
    return re.sub(r"[ \t\u3000\xa0]+", " ", text).strip().strip("《》「」『』")


def _extract_author_from_text(text: str) -> str:
    """从“作者：罗贯中”或纯“罗贯中”文本里提取作者名。"""
    text = _normal_text(text)
    if not text:
        return ""
    m = re.search(r"(?:作者|作者名|著者|原作者)\s*[:：]?\s*([^\s，。;；、|_\-—·：]{1,40})", text, re.I)
    if m:
        return _normal_text(m.group(1))
    # 短的纯姓名文本（避免“作者简介”等导航）
    if len(text) <= 30 and not re.search(r"简介|推荐|热门|公告|更多|返回|下一章|上一章|目录|列表", text, re.I):
        return text
    return ""


def _pick_title_from_document_title(raw: str, chapter_title: str = "") -> str:
    """从 <title> 中排除章节名、站点后缀，挑出最像书名的部分。"""
    raw = _normal_text(raw)
    if not raw:
        return ""
    parts = [p.strip() for p in _TITLE_SEP_RE.split(raw) if p.strip()]
    if chapter_title:
        chapter = _normal_text(chapter_title)
        if chapter:
            parts = [p for p in parts if _normal_text(p) not in (chapter,)]
    # 去掉常见站点/栏目后缀
    parts = [p for p in parts if not _TITLE_SUFFIX_RE.search(p)]
    if not parts:
        return ""
    # 优先含“书/小说/传/记/录/志/文集/合集/外传/正传”的片段
    for p in parts:
        if re.search(r"(小说|书|传|记|录|志|文集|合集|外传|正传|选集|全集)", p):
            return p
    parts = [p for p in parts if len(p) <= 40]
    if not parts:
        return ""
    return max(parts, key=len)


def extract_book_metadata(page: Page, chapter_title: str = "") -> tuple:
    """从章节页/目录页提取书名与作者；提取不到时返回空字符串。

    顺序参考 NovelGetter 的 #content / .bookname / 作者标记解析思路：
      1) 页面上 bookname/book-title 等容器
      2) <title> 去掉章节名与站点后缀后的片段
      3) 非章节标题的 h1/h2
      4) <meta name=author> / itemprop、作者 id/class 容器
    """
    if page is None or page.soup is None:
        return "", ""
    soup = page.soup
    if not chapter_title:
        chapter_title = extract_chapter_title(page, None)
    title, author = "", ""

    # 1) 显式书名容器
    title_candid = ""
    for el in soup.find_all(["div", "a", "h1", "h2", "h3", "span", "td"]):
        idc = _element_id_class(el)
        if not _BOOK_TITLE_IDCLASS_RE.search(idc):
            continue
        text = _normal_text(_BOOK_TITLE_PREFIX_RE.sub("", el.get_text(" ", strip=True)))
        if not text or len(text) > 60:
            continue
        if re.search(r"(上一章|下一章|目录|列表|简介|返回|首页|收藏|登录|注册)", text, re.I):
            continue
        if re.search(r"^(第[\d零一二三四五六七八九十百千万]+(章|回|节|卷)|chapter\s*\d+)", text, re.I):
            continue
        if len(text) > len(title_candid):
            title_candid = text
    if title_candid:
        title = title_candid

    # 2) <title>
    if not title and soup.title and soup.title.get_text(strip=True):
        title = _pick_title_from_document_title(
            soup.title.get_text(strip=True), chapter_title)

    # 3) h1/h2（排除章节标题）
    if not title:
        for el in soup.find_all(["h1", "h2"], limit=8):
            text = _normal_text(el.get_text(" ", strip=True))
            if not text or len(text) > 40:
                continue
            if chapter_title and text == _normal_text(chapter_title):
                continue
            if re.search(r"(上一章|下一章|目录|列表|简介|返回|首页|收藏|登录|注册|正文)", text, re.I):
                continue
            title = text
            break

    # 4) 作者
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        if name in ("author", "og:author", "og:novel:author", "creator"):
            author = _normal_text(meta.get("content", "")) or _normal_text(meta.get("value", ""))
            if author:
                break
    if not author:
        author_els = soup.select('[itemprop="author"], [itemprop="creator"]')
        for el in author_els:
            author = _extract_author_from_text(el.get_text(" ", strip=True))
            if author:
                break
    if not author:
        for el in soup.find_all(["div", "span", "p", "td", "a", "li"]):
            idc = _element_id_class(el)
            if not _AUTHOR_IDCLASS_RE.search(idc):
                continue
            author = _extract_author_from_text(el.get_text(" ", strip=True))
            if author:
                break

    return title, author


_PAGE_NEXT_RE = re.compile(r"下一页|下页|下一頁|下頁|next page", re.I)
# 正文分页增强：遍历全页链接寻找后续页（数字页码/容器外分页）
_PAGE_NEXT_TEXT_RE = re.compile(r"(下一页|下页|下一頁|下頁|next\s*page|›|»|→)", re.I)
_PAGE_EXCLUDE_TEXT_RE = re.compile(r"(上一页|上一頁|末页|最后一页|返回|目录|目錄|回目录|卷首|卷末)", re.I)
_PAGE_NUM_TEXT_RE = re.compile(r"^\s*(\d{1,3})\s*$")
_PAGE_FRAC_TEXT_RE = re.compile(r"^\s*(\d{1,3})\s*/\s*(\d{1,3})\s*$")
_PAGE_CONTAINER_RE = re.compile(
    r"(^|[\s_\-])(page|pages|pagination|pager|listpage|pagebar|fy|page-box|"
    r"chapter-page|content-page|article-page|page_area|turnpage|page-list)([^a-z]|$)",
    re.I)
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


# ---------- 正文分页增强：遍历全页链接寻找后续页 ----------


def _in_pagination_container(a) -> bool:
    """链接是否位于分页控件内（自身或祖先 id/class 含 page 等关键词）。"""
    cur = a
    for _ in range(6):  # 向上最多 6 层
        idc = _element_id_class(cur)
        if _PAGE_CONTAINER_RE.search(idc):
            return True
        if cur.parent is None:
            break
        cur = cur.parent
    return False


def _url_numbers(url: str):
    """提取 URL basename 末尾数字（g1_2.html → 主干 'g1_', 页码 2）。"""
    from urllib.parse import urlparse
    import posixpath
    base = posixpath.basename(urlparse(url).path)
    # 取最后一个数字段（页码位）：g1_2.html -> (g1_, 2)；3.html -> ("", 3)
    m = re.search(r"(\d+)(?!.*\d)\.\w*$", base)
    if not m:
        return (base.rsplit(".", 1)[0], None, ".html")
    return (base[: m.start(1)], int(m.group(1)), base[m.end(1):])


def _same_pagination_series(cur: str, cand: str) -> bool:
    """候选 URL 是否属于当前章节的分页系列（宽松判断，标题比对兜底）。"""
    from urllib.parse import urlparse, parse_qs
    import posixpath
    p1, p2 = urlparse(cur), urlparse(cand)
    if p1.netloc != p2.netloc:
        return False
    if p1.path == p2.path:
        q1, q2 = parse_qs(p1.query), parse_qs(p2.query)
        for key in ("page", "p", "pageNum", "page_num", "curPage"):
            if key in q1 and key in q2:
                try:
                    return int(q2[key][0]) > int(q1[key][0])
                except ValueError:
                    return False
        return False
    if posixpath.dirname(p1.path) != posixpath.dirname(p2.path):
        return False
    stem1, n1, suf1 = _url_numbers(cur)
    stem2, n2, suf2 = _url_numbers(cand)
    if n1 is not None and n2 is not None:
        if stem1 == stem2 and suf1 == suf2 and n2 > n1:
            return True
        # 当前主干 + 页码后缀：3.html -> 3_2.html / g1.html -> g1_2.html
        # （章节号可能大于页码，故不比较数值；是否同章由标题比对兜底）
        if stem2 != stem1 and stem2.startswith(stem1):
            return True
        return False
    if n2 is not None:
        return stem2.startswith(stem1)
    return False


def _adjacent_page_number(cur: str, cand: str) -> bool:
    """候选是否为当前页的紧邻下一页（页码 +1）。仅用于数字页码类候选。"""
    from urllib.parse import urlparse, parse_qs
    p1, p2 = urlparse(cur), urlparse(cand)
    if p1.path == p2.path:
        q1, q2 = parse_qs(p1.query), parse_qs(p2.query)
        for key in ("page", "p", "pageNum", "page_num", "curPage"):
            if key in q1 and key in q2:
                try:
                    return int(q2[key][0]) == int(q1[key][0]) + 1
                except ValueError:
                    return False
        return False
    _, n1, _ = _url_numbers(cur)
    _, n2, _ = _url_numbers(cand)
    if n1 is None:
        return n2 == 2
    return n2 == n1 + 1


def find_pagination_candidates(page: Page, container) -> list:
    """遍历当前页所有可跳转链接，寻找后续分页（支持容器外分页与数字页码）。

    候选来源（任一命中）：
      1) 链接文本“下一页/下页/next page/›/»”（排除“下一章/目录/上一页”）
      2) 链接 rel="next"
      3) 链接文本为纯数字页码（如 “2” “3”），且 URL 数字紧邻当前页 +1
      4) 链接位于分页控件内（id/class 含 page/pagination 等），且 URL 紧邻递增

    安全性：候选必须与当前 URL 同站点、同目录、且属于同一数字系列
    （章节页 g1.html → g1_2.html / g1_3.html；纯数字页 3.html → 4.html；
    ?page=2 → ?page=3）。是否同章由调用方抓取后比对章节核心确认。
    """
    soup = page.soup
    if soup is None:
        return []
    scopes = [container] if container is not None else []
    scopes.append(soup)
    scored = {}  # url -> 分数
    for scope in scopes:
        for a in scope.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            abs_url = page.resolve(href)
            if abs_url == page.url or abs_url in scored:
                continue
            text = a.get_text(" ", strip=True)
            title = a.get("title") or ""
            rel = a.get("rel") or []
            combined = f"{text} {title}"

            score = 0
            is_next_text = False
            if _PAGE_NEXT_TEXT_RE.search(combined) and not _CHAPTER_NEXT_RE.search(
                    combined) and not _PAGE_EXCLUDE_TEXT_RE.search(combined):
                score = max(score, 4)
                is_next_text = True
            if isinstance(rel, list) and "next" in rel:
                score = max(score, 4)
                is_next_text = True
            if _PAGE_NUM_TEXT_RE.match(text) or _PAGE_FRAC_TEXT_RE.match(text):
                score = max(score, 2)
            if _in_pagination_container(a):
                score = max(score, 1)
            if score == 0:
                continue
            if not _same_pagination_series(page.url, abs_url):
                continue
            if not is_next_text and not _adjacent_page_number(page.url, abs_url):
                continue
            scored[abs_url] = max(scored.get(abs_url, 0), score)
    out = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return [u for u, _ in out]


_CORE_ZH_RE = re.compile(r"第[\d零一二三四五六七八九十百千万]+(章|回|节|卷)")
_CORE_EN_RE = re.compile(r"(chapter|volume|part|book)\s*\d+", re.I)


def chapter_core(title: str) -> str:
    """提取章节核心标识用于分页比对。

    “第3章(2/3)” 与 “第3章” 视为同一章；与 “第4章” 视为不同章。
    """
    if not title:
        return ""
    t = _TITLE_SEP_RE.sub("", title.strip())
    m = _CORE_ZH_RE.search(t)
    if m:
        return m.group(0)
    m = _CORE_EN_RE.search(t)
    if m:
        return m.group(0).lower()
    return t[:8]
