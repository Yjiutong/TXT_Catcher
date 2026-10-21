# -*- coding: utf-8 -*-
"""TXT_Catcher 桌面应用入口：阅读浏览器 + 捕获包整理。

布局：一体式深色顶部栏（品牌 + 窗口控制，无边框可拖动）+ 左侧边栏导航
      + 右侧内容区；首页为「阅读浏览器」。从顶部输入网址，浏览页面并捕获
      疑似小说正文 / 目录的文本，导出捕获包交给 Codex 整理为 EPUB。
运行：python app.py  （或双击 run.bat / 使用打包后的 exe）
"""
import ctypes
import ctypes.wintypes
import os
import queue
import sys
import threading
import time

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from novel_catcher.config import Config
from novel_catcher.db import DB
from novel_catcher.manager import DownloadManager
from novel_catcher.crawler.http import HttpFetcher
from novel_catcher.crawler import discover
from novel_catcher.crawler.rules import get_rules
from novel_catcher import utils
from novel_catcher.capture import CaptureSession, kind_label
from novel_catcher import __version__

APP_TITLE = "TXT_Catcher 阅读捕获浏览器"
FONT = "Microsoft YaHei UI"

# 配色
HEADER_BG = "#1e293b"      # 顶部栏 / 侧边栏（一体深色）
SIDEBAR_BG = "#1e293b"
NAV_FG = "#cbd5e1"
NAV_ACTIVE_BG = "#2f6fed"
NAV_ACTIVE_FG = "#ffffff"
NAV_HOVER_BG = "#334155"
CONTENT_BG = "#ffffff"
ACCENT = "#2f6fed"
MUTED = "#94a3b8"

TITLEBAR_H = 48             # 顶部栏高度
CONTROL_ZONE = 150          # 右侧窗口控制按钮区宽度（避免误拖）

# Windows 窗口样式：无边框(popup)窗口默认带 WS_EX_TOOLWINDOW，不进任务栏/Alt+Tab；
# 需清除 TOOLWINDOW 并加 WS_EX_APPWINDOW 强制显示，任务栏图标跟随窗口图标
GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


class _MONITORINFO(ctypes.Structure):
    """GetMonitorInfoW 所需结构（ctypes.wintypes 未提供）。"""
    _fields_ = [("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD)]

STATUS_TEXT = {
    "queued": "排队中",
    "running": "下载中",
    "done": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def resource_path(rel: str) -> str:
    """定位打包资源（PyInstaller 解包目录 / 源码目录）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class TitleBar(tk.Frame):
    """一体式顶部栏：品牌 + 标题 + 窗口控制按钮（─ □ ×）。"""

    def __init__(self, app, parent):
        super().__init__(parent, bg=HEADER_BG, height=TITLEBAR_H)
        self.app = app
        self._maximized = False
        self._normal_geom = None
        self.pack_propagate(False)

        tk.Label(self, text="TXT_Catcher", font=(FONT, 13, "bold"),
                 fg="#ffffff", bg=HEADER_BG).grid(
            row=0, column=0, sticky="w", padx=(18, 0))
        tk.Label(self, text="公版小说阅读捕获 · 导出交给 Codex 整理 EPUB", font=(FONT, 10),
                 fg=MUTED, bg=HEADER_BG).grid(
            row=0, column=1, sticky="w", padx=(12, 0))
        self.columnconfigure(2, weight=1)

        ctl = tk.Frame(self, bg=HEADER_BG)
        ctl.grid(row=0, column=3, sticky="e")
        self._ctl_btn(ctl, "─", 17, self._minimize)
        self._max_btn = self._ctl_btn(ctl, "□", 17, self._toggle_maximize)
        self._ctl_btn(ctl, "✕", 18, self._close, danger=True)

    def _ctl_btn(self, parent, text, padx, cmd, danger=False):
        b = tk.Button(parent, text=text, font=(FONT, 12), bg=HEADER_BG,
                      fg="#e2e8f0", relief="flat", bd=0, padx=padx, pady=12,
                      activebackground="#475569", activeforeground="#ffffff",
                      cursor="hand2", command=cmd)
        b.pack(side="left")
        hover = "#e81123" if danger else "#334155"
        b.bind("<Enter>", lambda e, bb=b: bb.config(bg=hover))
        b.bind("<Leave>", lambda e, bb=b: bb.config(bg=HEADER_BG))
        return b

    # ---------- 窗口控制 ----------
    def _toggle_maximize(self):
        root = self.app.root
        if self._maximized:
            if self._normal_geom:
                root.geometry(self._normal_geom)
            self._maximized = False
        else:
            self._normal_geom = root.geometry()
            w, h, x, y = self._work_area(self.app._ensure_hwnd())
            root.geometry(f"{w}x{h}+{x}+{y}")
            self._maximized = True

    def _minimize(self):
        # ShowWindow(SW_MINIMIZE)：保留任务栏按钮，点击任务栏即可恢复
        hwnd = self.app._ensure_hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE

    def _close(self):
        self.app._on_close()

    @staticmethod
    def _work_area(hwnd=None):
        """窗口所在显示器的工作区，换算为 Tk 逻辑像素（避免高 DPI 下最大化盖住任务栏）。

        换算方式：物理像素 * (Tk 屏幕尺寸 / 物理屏幕尺寸)。进程无论是否 DPI 感知，
        该比例都成立；100% DPI 时比例为 1，行为与之前一致。
        """
        try:
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if hwnd:
                mon = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)  # 最近显示器
            else:
                mon = ctypes.windll.user32.MonitorFromPoint(0, 0, 1)   # 主显示器
            if not mon or not ctypes.windll.user32.GetMonitorInfoW(
                    mon, ctypes.byref(info)):
                raise RuntimeError("GetMonitorInfoW failed")
            root = tk._default_root
            lw = root.winfo_screenwidth()
            lh = root.winfo_screenheight()
            sx = lw / max(1, info.rcMonitor.right - info.rcMonitor.left)
            sy = lh / max(1, info.rcMonitor.bottom - info.rcMonitor.top)
            w = int((info.rcWork.right - info.rcWork.left) * sx)
            h = int((info.rcWork.bottom - info.rcWork.top) * sy)
            x = int(info.rcWork.left * sx)
            y = int(info.rcWork.top * sy)
            return (w, h, x, y)
        except Exception:
            root = tk._default_root
            if root is not None:
                return (root.winfo_screenwidth(), root.winfo_screenheight(), 0, 0)
            return (1024, 768, 0, 0)


class AddPanel(tk.Frame):
    """首页面板：新建下载（书名/作者/章节网址 + 预览 + 开始下载）。

    与下载任务同处一页：点击「开始下载」后，任务立即出现在下方任务列表。
    """

    def __init__(self, app, parent):
        super().__init__(parent, bg=CONTENT_BG)
        self.app = app
        self._preview_result = []
        self._build()

    def _build(self):
        pad = {"padx": 14, "pady": 8}
        outer = tk.Frame(self, bg=CONTENT_BG)
        outer.pack(fill="x", padx=40, pady=(22, 10))

        tk.Label(outer, text="新建下载", font=(FONT, 22, "bold"),
                 fg="#0f172a", bg=CONTENT_BG).pack(anchor="w")
        tk.Label(outer, text="粘贴书中的几章网址，自动推测整本书并整合为 TXT + EPUB",
                 font=(FONT, 11), fg="#64748b", bg=CONTENT_BG).pack(anchor="w", pady=(2, 14))

        form = tk.Frame(outer, bg=CONTENT_BG)
        form.pack(fill="x")

        # 书名 / 作者
        tk.Label(form, text="书名（留空则自动提取）", font=(FONT, 10),
                 fg="#334155", bg=CONTENT_BG).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.title_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.title_var, font=(FONT, 11)).grid(
            row=1, column=0, sticky="ew", padx=(0, 10), pady=(0, 10))

        tk.Label(form, text="作者（可选）", font=(FONT, 10),
                 fg="#334155", bg=CONTENT_BG).grid(row=0, column=1, sticky="w", pady=(0, 6))
        self.author_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.author_var, font=(FONT, 11)).grid(
            row=1, column=1, sticky="ew", pady=(0, 10))

        tk.Label(form, text="章节网址（提供其中几章即可，每行一个）", font=(FONT, 10),
                 fg="#334155", bg=CONTENT_BG).grid(row=2, column=0, columnspan=2, sticky="w")
        self.urls_text = tk.Text(form, height=6, font=(FONT, 11),
                                 relief="solid", bd=1, highlightthickness=1,
                                 highlightbackground="#cbd5e1", highlightcolor=ACCENT,
                                 wrap="word", bg="#fbfcfe", padx=8, pady=6)
        self.urls_text.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 12))

        btns = tk.Frame(form, bg=CONTENT_BG)
        btns.grid(row=4, column=0, columnspan=2, sticky="w")
        self.preview_btn = tk.Button(
            btns, text="预览章节位置", font=(FONT, 11), cursor="hand2",
            bg="#eef2ff", fg="#1e40af", activebackground="#e0e7ff",
            activeforeground="#1e40af", relief="flat", padx=18, pady=6,
            command=self.preview)
        self.preview_btn.pack(side="left")
        self.start_btn = tk.Button(
            btns, text="开始下载", font=(FONT, 11, "bold"), cursor="hand2",
            bg=ACCENT, fg="#ffffff", activebackground="#1d4ed8",
            activeforeground="#ffffff", relief="flat", padx=24, pady=6,
            command=self.start)
        self.start_btn.pack(side="left", padx=(12, 0))

        self.preview_var = tk.StringVar(value="")
        tk.Label(outer, textvariable=self.preview_var, font=(FONT, 10),
                 fg="#0a6", bg=CONTENT_BG, anchor="w", wraplength=880).pack(
            anchor="w", pady=(8, 0))

        form.columnconfigure(0, weight=3)
        form.columnconfigure(1, weight=2)
        form.rowconfigure(3, weight=1)

    # ---------- 预览 / 下载 ----------
    def _seeds(self):
        urls = []
        for line in self.urls_text.get("1.0", "end").splitlines():
            u = utils.normalize_url(line)
            if u and u.startswith(("http://", "https://")):
                urls.append(u)
        return urls

    def preview(self):
        seeds = self._seeds()
        if not seeds:
            messagebox.showwarning("提示", "请先粘贴至少一个章节网址", parent=self)
            return
        self.preview_btn.config(state="disabled", bg="#cbd5e1")
        self.preview_var.set("正在分析章节位置…")
        self._preview_result = []
        cfg = self.app.config

        def work():
            try:
                fetcher = HttpFetcher(cfg)
                urls = discover.discover_chapters(
                    fetcher, seeds, max_chapters=cfg.get("max_chapters"),
                    rules=get_rules(cfg))
                self._preview_result = (urls, "")
            except Exception as e:
                self._preview_result = ([], f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()
        self._poll_preview()

    def _poll_preview(self):
        if not self._preview_result:
            self.after(200, self._poll_preview)
            return
        urls, err = self._preview_result
        self.preview_btn.config(state="normal", bg="#eef2ff")
        if err:
            self.preview_var.set(f"分析失败：{err}")
            return
        shown = "、".join(urls[:3])
        more = f"… 共 {len(urls)} 章" if len(urls) > 3 else ""
        self.preview_var.set(f"已定位 {len(urls)} 个章节：{shown}{more}")

    def start(self):
        seeds = self._seeds()
        if not seeds:
            messagebox.showwarning("提示", "请先粘贴至少一个章节网址", parent=self)
            return
        try:
            self.app.manager.add_download(
                self.title_var.get().strip(), self.author_var.get().strip(), seeds)
        except ValueError as e:
            messagebox.showerror("错误", str(e), parent=self)
            return
        self.urls_text.delete("1.0", "end")
        self.preview_var.set("")
        self.app.status_var.set("已加入下载队列，正在下方任务列表运行")
        self.app._log(f"已加入队列：{self.title_var.get().strip() or '未命名'}")
        self.title_var.set("")
        self.author_var.set("")
        self.app.refresh_library()
        self.app.refresh_tasks()


class ReaderWindow(tk.Toplevel):
    """内置阅读器：左侧章节列表 + 右侧正文，支持字号调节与章节跳转。

    解析 TXT（exporter/txt.py 输出格式，`====`×30 分隔章节块）。
    """

    _SEP = "=" * 30
    _FONT_SIZES = (11, 12, 13, 14, 15, 16, 18, 20)

    def __init__(self, app, book):
        super().__init__(app.root)
        self.app = app
        self.title(f"阅读：{book['title'] or '未命名'} · {book['author'] or '佚名'}")
        self.geometry("980x680")
        self.minsize(680, 480)
        # 居中显示
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2)
        self.geometry(f"+{x}+{y}")

        path = book.get("txt_path") or ""
        if not path or not os.path.exists(path):
            messagebox.showinfo("提示", "该书暂无 TXT 文件可阅读", parent=self)
            self.destroy()
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            messagebox.showerror("阅读失败", f"无法读取 TXT：{e}", parent=self)
            self.destroy()
            return

        self._build(text)
        try:
            try:
                self.iconbitmap(resource_path(os.path.join("assets", "icon.ico")))
            except Exception:
                pass
            self.transient(app.root)  # 跟随主窗口
        except Exception:
            pass

    # ---------- 界面 ----------
    def _build(self, text: str):
        lines = text.split("\n")
        # 章节块：目录与正文由 `====`×30 分隔；每个分隔行后的首个非空行是章节标题。
        # （正文与目录间的那条分隔行（k=0）后即第 1 章，也要纳入索引）
        seps = [i for i, ln in enumerate(lines) if ln.strip() == self._SEP]
        self._chapters = []  # (标题, 起始行号)
        for k in range(len(seps)):
            start = seps[k] + 1
            j = start
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                break
            self._chapters.append((lines[j].strip(), j + 1))
        if not self._chapters:
            self._chapters = [("正文", 1)]

        # 顶部工具条：字号
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="字号").pack(side="left")
        self._font_i = 2  # 默认 13
        ttk.Button(bar, text="A−", width=4,
                   command=lambda: self._font(-1)).pack(side="left", padx=(6, 2))
        ttk.Button(bar, text="A＋", width=4,
                   command=lambda: self._font(1)).pack(side="left", padx=2)
        ttk.Label(bar, text=f"共 {len(self._chapters)} 章 · 点击左侧章节跳转",
                  foreground="#64748b").pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 左侧章节列表
        left = ttk.Frame(body, width=200)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.listbox = tk.Listbox(left, font=(FONT, 10), width=24,
                                  activestyle="none", exportselection=False)
        for title, _ in self._chapters:
            self.listbox.insert("end", title)
        lb_vsb = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=lb_vsb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        lb_vsb.pack(side="right", fill="y")
        self.listbox.bind("<ButtonRelease-1>", self._jump_selected)

        # 右侧正文
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.text = tk.Text(right, font=(FONT, self._FONT_SIZES[self._font_i]),
                            wrap="word", state="disabled", bg="#fffef8",
                            padx=24, pady=14, relief="flat")
        txt_vsb = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=txt_vsb.set)
        self.text.pack(side="left", fill="both", expand=True)
        txt_vsb.pack(side="right", fill="y")

        self.text.config(state="normal")
        self.text.insert("1.0", text)
        self.text.config(state="disabled")
        self._font_i = 2
        self._apply_font()
        if self._chapters:
            self.listbox.selection_set(0)
            self._jump(0)

    # ---------- 行为 ----------
    def _font(self, d: int):
        self._font_i = max(0, min(len(self._FONT_SIZES) - 1, self._font_i + d))
        self._apply_font()

    def _apply_font(self):
        self.text.configure(font=(FONT, self._FONT_SIZES[self._font_i]))

    def _jump_selected(self, _e=None):
        sel = self.listbox.curselection()
        if sel:
            self._jump(sel[0])

    def _jump(self, idx: int):
        if not (0 <= idx < len(self._chapters)):
            return
        line = self._chapters[idx][1]
        self.text.see(f"{line}.0")
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.see(idx)


class BrowserPanel(tk.Frame):
    """阅读浏览器主页：顶部地址栏 + 正文/目录阅读视图 + 捕获包侧栏。"""

    def __init__(self, app, parent):
        super().__init__(parent, bg=CONTENT_BG)
        self.app = app
        self.session = CaptureSession()
        self.url_var = tk.StringVar()
        self._history = []
        self._history_pos = -1
        self._q = queue.Queue()
        self._link_tags = {}
        self._next_link_id = 0
        self._busy = False
        self._build()
        self._poll()

    # ---------- 界面 ----------
    def _build(self):
        addr = tk.Frame(self, bg="#e2e8f0", padx=12, pady=8)
        addr.pack(fill="x")

        self.back_btn = tk.Button(addr, text="←", width=3, font=(FONT, 11),
                                  bg="#e2e8f0", fg="#334155", relief="flat", bd=0,
                                  cursor="hand2", command=self._go_back)
        self.back_btn.pack(side="left")
        self.forward_btn = tk.Button(addr, text="→", width=3, font=(FONT, 11),
                                     bg="#e2e8f0", fg="#334155", relief="flat", bd=0,
                                     cursor="hand2", command=self._go_forward)
        self.forward_btn.pack(side="left")
        self.refresh_btn = tk.Button(addr, text="↻", width=3, font=(FONT, 11),
                                     bg="#e2e8f0", fg="#334155", relief="flat", bd=0,
                                     cursor="hand2", command=self._refresh)
        self.refresh_btn.pack(side="left")

        self.url_entry = ttk.Entry(addr, textvariable=self.url_var, font=(FONT, 11))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.url_entry.bind("<Return>", lambda _e: self.navigate())
        self.go_btn = tk.Button(addr, text="前往", font=(FONT, 11, "bold"),
                                bg=ACCENT, fg="#ffffff", activebackground="#1d4ed8",
                                activeforeground="#ffffff", relief="flat", padx=16,
                                pady=4, cursor="hand2", command=self.navigate)
        self.go_btn.pack(side="left")

        body = tk.Frame(self, bg=CONTENT_BG)
        body.pack(fill="both", expand=True)

        # 右侧捕获包侧栏
        side = tk.Frame(body, bg="#f8fafc", width=270)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        ttk.Label(side, text="已捕获页面", font=(FONT, 12, "bold")).pack(
            anchor="w", padx=12, pady=(12, 4))
        self.capture_status_var = tk.StringVar(value="0 页，0 字")
        ttk.Label(side, textvariable=self.capture_status_var,
                  foreground="#64748b").pack(anchor="w", padx=12, pady=(0, 6))

        tree_frm = ttk.Frame(side)
        tree_frm.pack(fill="both", expand=True, padx=10)
        self.capture_tree = ttk.Treeview(
            tree_frm, columns=("kind", "title", "chars"), show="headings",
            selectmode="browse", height=12)
        self.capture_tree.heading("kind", text="类型")
        self.capture_tree.heading("title", text="标题")
        self.capture_tree.heading("chars", text="字数")
        self.capture_tree.column("kind", width=62, anchor="center")
        self.capture_tree.column("title", width=130)
        self.capture_tree.column("chars", width=54, anchor="center")
        tree_vsb = ttk.Scrollbar(tree_frm, orient="vertical",
                                 command=self.capture_tree.yview)
        self.capture_tree.configure(yscrollcommand=tree_vsb.set)
        self.capture_tree.pack(side="left", fill="both", expand=True)
        tree_vsb.pack(side="right", fill="y")
        self.capture_tree.bind("<Double-1>", lambda _e: self._open_capture_record())

        ctl = ttk.Frame(side, padding=(10, 8))
        ctl.pack(fill="x")
        ttk.Button(ctl, text="导出捕获包", command=self._export_capture).pack(
            side="left", fill="x", expand=True)
        ttk.Button(ctl, text="清空", command=self._clear_capture).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        # 左侧阅读视图
        main = tk.Frame(body, bg=CONTENT_BG)
        main.pack(side="left", fill="both", expand=True)
        self.page_text = tk.Text(main, font=(FONT, 13), wrap="word", undo=False,
                                 bg="#fffef8", fg="#0f172a", relief="flat",
                                 padx=28, pady=18)
        page_vsb = ttk.Scrollbar(main, orient="vertical", command=self.page_text.yview)
        self.page_text.configure(yscrollcommand=page_vsb.set)
        self.page_text.pack(side="left", fill="both", expand=True)
        page_vsb.pack(side="right", fill="y")
        self.page_text.tag_configure("head", font=(FONT, 22, "bold"), foreground="#0f172a")
        self.page_text.tag_configure("meta", font=(FONT, 10), foreground="#64748b")
        self.page_text.tag_configure("section", font=(FONT, 12, "bold"), foreground="#334155")
        self.page_text.tag_configure("link", foreground="#1e40af", underline=1)
        self.page_text.tag_configure("bad", foreground="#b91c1c")
        self.page_text.bind("<Button-1>", self._on_text_click)

        tk.Label(main, text="在顶部输入网址，然后把浏览中看到的小说正文/目录页直接收集到右侧捕获包。",
                 font=(FONT, 9), fg="#94a3b8", bg=CONTENT_BG).pack(
            side="bottom", anchor="w", padx=28, pady=(0, 8))

    # ---------- 地址栏行为 ----------
    def navigate(self, url=None, from_history=False):
        url = utils.normalize_url(url or self.url_var.get())
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        self.url_var.set(url)
        if not from_history:
            self._history = self._history[: self._history_pos + 1]
            self._history.append(url)
            self._history_pos = len(self._history) - 1
        self._do_fetch(url)

    def _refresh(self):
        if self._history:
            self._do_fetch(self._history[self._history_pos])

    def _go_back(self):
        if self._history_pos > 0:
            self._history_pos -= 1
            self.navigate(self._history[self._history_pos], from_history=True)

    def _go_forward(self):
        if self._history_pos + 1 < len(self._history):
            self._history_pos += 1
            self.navigate(self._history[self._history_pos], from_history=True)

    def _update_nav_buttons(self):
        self.back_btn.config(state="normal" if self._history_pos > 0 else "disabled")
        self.forward_btn.config(
            state="normal" if self._history_pos + 1 < len(self._history) else "disabled")

    def _do_fetch(self, url):
        if self._busy:
            return
        self._busy = True
        self.go_btn.config(state="disabled", text="加载中…")
        self.refresh_btn.config(state="disabled")
        self.app.status_var.set(f"正在打开：{url}")
        threading.Thread(target=self._fetch_work, args=(url,), daemon=True).start()

    def _fetch_work(self, url: str):
        try:
            fetcher = HttpFetcher(self.app.config)
            page = fetcher.fetch(url)
            rules = get_rules(self.app.config)
            rec = self.session.add(page, rules=rules)
            self._q.put(("ok", rec))
        except Exception as e:
            self._q.put(("err", url, str(e)))

    def _poll(self):
        try:
            while True:
                msg = self._q.get_nowait()
                if msg[0] == "ok":
                    self._on_fetch_ok(msg[1])
                else:
                    self._on_fetch_err(msg[1], msg[2])
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _on_fetch_ok(self, rec):
        self.url_var.set(rec.get("final_url") or rec.get("url") or "")
        self._busy = False
        self.go_btn.config(state="normal", text="前往")
        self.refresh_btn.config(state="normal")
        self._update_nav_buttons()
        self._render(rec)
        self._refresh_capture_tree()
        self.app.status_var.set(
            f"{kind_label(rec['kind'])}：{rec.get('title') or '(无标题)'}")

    def _on_fetch_err(self, url, err):
        self._busy = False
        self.go_btn.config(state="normal", text="前往")
        self.refresh_btn.config(state="normal")
        self._update_nav_buttons()
        self.page_text.config(state="normal")
        self.page_text.delete("1.0", "end")
        self.page_text.insert("end", "无法打开页面\n", "head")
        self.page_text.insert("end", f"{url}\n\n{err}\n", "bad")
        self.page_text.config(state="disabled")
        self.app.status_var.set(f"打开失败：{url}")

    # ---------- 阅读视图 ----------
    def _render(self, rec):
        self._link_tags.clear()
        self._next_link_id = 0
        self.page_text.config(state="normal")
        self.page_text.delete("1.0", "end")

        title = rec.get("title") or "(无标题)"
        self.page_text.insert("end", f"{title}\n", "head")
        meta = []
        if rec.get("book_title"):
            meta.append(f"书名：{rec['book_title']}")
        if rec.get("author"):
            meta.append(f"作者：{rec['author']}")
        meta.append(f"分类：{kind_label(rec['kind'])}")
        url = rec.get("final_url") or rec.get("url") or ""
        meta.append(url)
        self.page_text.insert("end", " · ".join(meta) + "\n\n", "meta")

        nav = rec.get("nav") or {}
        if nav:
            self.page_text.insert("end", "── 本页导航 ──\n", "section")
            for key in ("toc", "prev", "next"):
                item = nav.get(key)
                if item:
                    self._insert_link(f"[{item['title']}]", item["url"])
            self.page_text.insert("end", "\n")

        toc = rec.get("toc_items") or []
        if toc:
            self.page_text.insert("end", f"── 目录候选（{len(toc)} 条）──\n", "section")
            for i, item in enumerate(toc, 1):
                self._insert_link(f"{i}. {item.get('title', '(无标题)')}",
                                  item.get("url", ""))
            self.page_text.insert("end", "\n")

        paras = rec.get("paragraphs") or []
        if paras:
            self.page_text.insert("end", "── 正文候选 ──\n\n", "section")
            self.page_text.insert("end", "\n\n".join(paras) + "\n")

        links = rec.get("links") or []
        if links and not toc:
            self.page_text.insert("end", f"\n── 本页链接（{len(links)} 条，点击可浏览）──\n",
                                  "section")
            for item in links[:50]:
                self._insert_link(item.get("title", "(无标题)"), item.get("url", ""))

        self.page_text.config(state="disabled")

    def _insert_link(self, label, url):
        if not url:
            self.page_text.insert("end", f"  {label}\n")
            return
        tag = f"url:{self._next_link_id}"
        self._next_link_id += 1
        self._link_tags[tag] = url
        self.page_text.insert("end", f"  {label}\n", ("link", tag))

    def _on_text_click(self, e):
        idx = self.page_text.index(f"@{e.x},{e.y}")
        for tag in self.page_text.tag_names(idx):
            if tag.startswith("url:"):
                url = self._link_tags.get(tag)
                if url:
                    self.navigate(url)
                break

    # ---------- 捕获包 ----------
    def _refresh_capture_tree(self):
        for i in self.capture_tree.get_children():
            self.capture_tree.delete(i)
        for i, rec in enumerate(self.session.records):
            self.capture_tree.insert("", "end", iid=str(i), values=(
                kind_label(rec.get("kind")),
                (rec.get("title") or "(无标题)")[:24],
                rec.get("char_count") or 0))
        s = self.session.summary()
        self.capture_status_var.set(
            f"{s['pages']} 页 · {s['chapter_pages'] + s['toc_pages']} 疑似 · "
            f"{utils.format_word_count(s['chars'])} 字")
        self.app.status_var.set(
            f"已捕获 {s['pages']} 页，其中目录候选 {s['toc_pages']}、正文候选 {s['chapter_pages']}")

    def _open_capture_record(self):
        sel = self.capture_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.session.records):
            self._render(self.session.records[idx])

    def _export_capture(self):
        if not self.session.records:
            messagebox.showinfo("提示", "还没有捕获任何页面", parent=self)
            return
        out_dir = os.path.join(self.app.config.get("output_dir"), "capture_packages")
        try:
            zip_path = self.session.save_package(out_dir)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)
            return
        self.app.status_var.set("捕获包已导出")
        messagebox.showinfo(
            "捕获包已导出",
            f"已生成 Codex 捕获包：\n{zip_path}\n\n"
            "可以在新对话中把这个 zip 交给 Codex，使用 "
            "skills/novel_pack_to_epub 整理为 EPUB。",
            parent=self)

    def _clear_capture(self):
        if not self.session.records:
            return
        if not messagebox.askyesno("清空捕获包", "确定清空当前已捕获的页面？", parent=self):
            return
        self.session = CaptureSession()
        self._refresh_capture_tree()
        self.page_text.config(state="normal")
        self.page_text.delete("1.0", "end")
        self.page_text.config(state="disabled")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = Config()
        from novel_catcher.config import DEFAULT_DB_PATH
        self.db = DB(DEFAULT_DB_PATH)
        self.manager = DownloadManager(self.db, self.config, logger=self._log)
        self._build_ui()
        self._poll_events()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 界面 ----------
    def _build_ui(self):
        self.root.title(APP_TITLE)
        w, h = 1020, 680
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(900, 580)

        # 窗口 / 任务栏图标
        try:
            self.root.iconbitmap(resource_path(os.path.join("assets", "icon.ico")))
        except Exception:
            pass

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Treeview", rowheight=26, font=(FONT, 10))
        style.configure("Treeview.Heading", font=(FONT, 10, "bold"))
        style.configure("TButton", font=(FONT, 10))
        style.configure("TLabel", font=(FONT, 10))
        style.configure("TLabelframe.Label", font=(FONT, 10))

        # 无边框窗口 + 一体式顶部栏
        self.root.overrideredirect(True)
        self._hwnd = None
        # 顶层句柄在窗口映射时才创建；<Map> 触发时必然可获取
        self.root.bind("<Map>", lambda _e: self._set_taskbar_style())
        self._set_taskbar_style()

        main = tk.Frame(self.root, bg=HEADER_BG)
        main.pack(fill="both", expand=True)

        self.titlebar = TitleBar(self, main)
        self.titlebar.pack(side="top", fill="x")

        body = tk.Frame(main, bg=SIDEBAR_BG)
        body.pack(fill="both", expand=True)

        # ---- 左侧边栏 ----
        sidebar = tk.Frame(body, bg=SIDEBAR_BG, width=178)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self._nav_btns = {}
        nav_items = [
            ("browser", "◉  阅读浏览"),
            ("library", "▤  书籍库"),
            ("settings", "⚙  设置"),
        ]
        for key, text in nav_items:
            b = tk.Button(sidebar, text=text, font=(FONT, 11), anchor="w",
                          bg=SIDEBAR_BG, fg=NAV_FG, relief="flat", bd=0,
                          activebackground=NAV_HOVER_BG, activeforeground=NAV_FG,
                          cursor="hand2", padx=18, pady=9,
                          command=lambda k=key: self._show_page(k))
            b.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = b

        tk.Label(sidebar, text=f"v{__version__} · 仅限公版作品",
                 font=(FONT, 8), fg="#64748b", bg=SIDEBAR_BG).pack(
            side="bottom", anchor="w", padx=18, pady=14)

        # ---- 右侧内容区 ----
        self.content = tk.Frame(body, bg=CONTENT_BG)
        self.content.pack(side="left", fill="both", expand=True)

        # 首页 = 阅读浏览器 + 捕获包侧栏
        self.page_home = tk.Frame(self.content, bg=CONTENT_BG)
        self.browser_panel = BrowserPanel(self, self.page_home)
        self.browser_panel.pack(fill="both", expand=True)

        self.page_library = tk.Frame(self.content, bg=CONTENT_BG)
        self.page_settings = tk.Frame(self.content, bg=CONTENT_BG)
        for page in (self.page_home, self.page_library, self.page_settings):
            page.grid(row=0, column=0, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self._build_library_page()
        self._build_settings_page()
        self._show_page("browser")

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                  font=(FONT, 9)).pack(fill="x", padx=12, pady=(0, 6))

        # 无边框窗口的拖动 / 边缘缩放
        self._resize_start = None
        self._drag_off = None
        self._edge_zone_now = None
        self._cursor_owned = False
        self.root.bind("<Motion>", self._on_motion)
        self.root.bind("<ButtonPress-1>", self._on_b1_press)
        self.root.bind("<B1-Motion>", self._on_b1_motion)
        self.root.bind("<ButtonRelease-1>", self._on_b1_release)
        self.root.bind("<Double-Button-1>", self._on_double_click)

        self._show_page("add")
        self.refresh_library()
        self.refresh_tasks()

    # ---------- 无边框窗口：移动 / 缩放 ----------
    _EDGE = 5
    _CURSORS = {"n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we",
                "nw": "size_nwse", "se": "size_nwse",
                "ne": "size_nesw", "sw": "size_nesw"}

    def _set_taskbar_style(self):
        """清除 WS_EX_TOOLWINDOW 并设置 WS_EX_APPWINDOW，使无边框窗口进入任务栏；
        任务栏图标跟随窗口图标（iconbitmap 设置的 ico）。返回是否成功。"""
        try:
            wid = self.root.winfo_id()
            hwnd = ctypes.windll.user32.GetParent(wid)
            if not hwnd:
                return False
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex &= ~WS_EX_TOOLWINDOW
            ex |= WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
            self._hwnd = hwnd
            return True
        except Exception:
            return False

    def _ensure_hwnd(self):
        """窗口句柄懒获取：窗口未完全创建时先取不到，重试补上。"""
        if not self._hwnd:
            self._set_taskbar_style()
        return self._hwnd

    def _edge_zone(self, rx, ry):
        if self.titlebar._maximized:
            return None
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        e = self._EDGE
        north, south = ry <= e, ry >= h - e
        west, east = rx <= e, rx >= w - e
        if north and west:
            return "nw"
        if north and east:
            return "ne"
        if south and west:
            return "sw"
        if south and east:
            return "se"
        if north:
            return "n"
        if south:
            return "s"
        if west:
            return "w"
        if east:
            return "e"
        return None

    def _on_motion(self, e):
        rx = e.x_root - self.root.winfo_rootx()
        ry = e.y_root - self.root.winfo_rooty()
        zone = self._edge_zone(rx, ry)
        self._edge_zone_now = zone
        if zone:
            self.root.config(cursor=self._CURSORS[zone])
            self._cursor_owned = True
        elif self._cursor_owned:
            self.root.config(cursor="")
            self._cursor_owned = False

    def _on_b1_press(self, e):
        rx = e.x_root - self.root.winfo_rootx()
        ry = e.y_root - self.root.winfo_rooty()
        zone = self._edge_zone_now if not self.titlebar._maximized else None
        w = self.root.winfo_width()
        if zone:
            self._resize_start = (zone, e.x_root, e.y_root,
                                  self.root.winfo_x(), self.root.winfo_y(),
                                  w, self.root.winfo_height())
            self._drag_off = None
        elif ry <= TITLEBAR_H and rx <= w - CONTROL_ZONE:
            self._drag_off = (e.x_root - self.root.winfo_x(),
                              e.y_root - self.root.winfo_y())
            self._resize_start = None
        else:
            self._resize_start = None
            self._drag_off = None

    def _on_b1_motion(self, e):
        if self.titlebar._maximized:
            return
        if self._resize_start:
            zone, sx, sy, wx, wy, ww, wh = self._resize_start
            min_w, min_h = self.root.minsize()
            dx, dy = e.x_root - sx, e.y_root - sy
            x, y, w, h = wx, wy, ww, wh
            if "e" in zone:
                w = max(min_w, ww + dx)
            if "s" in zone:
                h = max(min_h, wh + dy)
            if "w" in zone:
                w = max(min_w, ww - dx)
                x = wx + (ww - w)
            if "n" in zone:
                h = max(min_h, wh - dy)
                y = wy + (wh - h)
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        elif self._drag_off:
            self.root.geometry(f"+{e.x_root - self._drag_off[0]}+{e.y_root - self._drag_off[1]}")

    def _on_b1_release(self, _e):
        self._resize_start = None
        self._drag_off = None

    def _on_double_click(self, e):
        rx = e.x_root - self.root.winfo_rootx()
        ry = e.y_root - self.root.winfo_rooty()
        w = self.root.winfo_width()
        if ry <= TITLEBAR_H and rx <= w - CONTROL_ZONE:
            self.titlebar._toggle_maximize()

    # ---------- 页面切换 ----------
    def _show_page(self, key: str):
        """切换右侧页面并高亮侧边栏按钮。"""
        pages = {"browser": self.page_home, "add": self.page_home, "library": self.page_library,
                 "settings": self.page_settings}
        page = pages.get(key)
        if page is None:
            return
        page.tkraise()
        for k, b in self._nav_btns.items():
            if k == key:
                b.config(bg=NAV_ACTIVE_BG, fg=NAV_ACTIVE_FG,
                         activebackground=NAV_ACTIVE_BG, activeforeground=NAV_ACTIVE_FG)
            else:
                b.config(bg=SIDEBAR_BG, fg=NAV_FG,
                         activebackground=NAV_HOVER_BG, activeforeground=NAV_FG)

    # ---------- 书籍库页 ----------
    def _build_library_page(self):
        frm = ttk.Frame(self.page_library, padding=10)
        frm.pack(fill="both", expand=True)

        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="◉ 去阅读浏览", command=lambda: self._show_page("browser")).pack(side="left")
        ttk.Button(bar, text="刷新", command=self.refresh_library).pack(side="left", padx=6)
        ttk.Button(bar, text="打开输出目录", command=self._open_output_dir).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="打开TXT", command=lambda: self._open_selected("txt")).pack(side="left")
        ttk.Button(bar, text="打开EPUB", command=lambda: self._open_selected("epub")).pack(side="left", padx=6)
        ttk.Button(bar, text="重新下载", command=self._redownload_selected).pack(side="left")
        ttk.Button(bar, text="删除记录", command=self._delete_selected).pack(side="left", padx=(6, 0))

        cols = ("id", "title", "author", "chapters", "words", "status", "time")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        heads = {"id": ("ID", 44), "title": ("书名", 250), "author": ("作者", 120),
                 "chapters": ("章节", 64), "words": ("字数", 90),
                 "status": ("状态", 90), "time": ("更新时间", 140)}
        for c, (t, wdt) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wdt, anchor="center" if c != "title" else "w")
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._read_selected())
        self.tree.bind("<Delete>", lambda e: self._delete_selected())
        # 行级右键菜单：阅读、打开 TXT/EPUB、重新下载、删除记录
        self._lib_menu = tk.Menu(self.tree, tearoff=0)
        self._lib_menu.add_command(label="开始阅读",
                                   command=lambda: self._read_selected())
        self._lib_menu.add_command(label="打开 TXT",
                                   command=lambda: self._open_selected("txt"))
        self._lib_menu.add_command(label="打开 EPUB",
                                   command=lambda: self._open_selected("epub"))
        self._lib_menu.add_command(label="重新下载", command=self._redownload_selected)
        self._lib_menu.add_separator()
        self._lib_menu.add_command(label="删除记录", command=self._delete_selected)
        self.tree.bind("<Button-3>", self._popup_lib_menu)

    # ---------- 下载任务区（位于首页下方） ----------
    def _build_tasks_section(self, parent):
        frm = ttk.Frame(parent, padding=(40, 4, 40, 10))
        frm.pack(fill="both", expand=True)

        head = ttk.Frame(frm)
        head.pack(fill="x", pady=(6, 4))
        ttk.Label(head, text="下载任务", font=(FONT, 13, "bold")).pack(side="left")
        ttk.Label(head, text="（点击「开始下载」后，任务会立即出现在这里）",
                  foreground="#64748b").pack(side="left", padx=10)

        self.task_tree = ttk.Treeview(frm, columns=("title", "pct", "stage"),
                                      show="headings", selectmode="browse", height=5)
        self.task_tree.heading("title", text="书名")
        self.task_tree.heading("pct", text="进度")
        self.task_tree.heading("stage", text="阶段")
        self.task_tree.column("title", width=320)
        self.task_tree.column("pct", width=90, anchor="center")
        self.task_tree.column("stage", width=360)
        self.task_tree.pack(fill="x")

        ttk.Label(frm, text="选中任务的进度：").pack(anchor="w", pady=(10, 2))
        self.progress = ttk.Progressbar(frm, maximum=100, value=0)
        self.progress.pack(fill="x")

        ttk.Label(frm, text="运行日志：").pack(anchor="w", pady=(10, 2))
        log_frm = ttk.Frame(frm)
        log_frm.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frm, height=12, font=(FONT, 9), state="disabled",
                                wrap="word", bg="#f7f7f7")
        log_vsb = ttk.Scrollbar(log_frm, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_vsb.pack(side="right", fill="y")

        ctl = ttk.Frame(frm)
        ctl.pack(fill="x", pady=(8, 0))
        ttk.Button(ctl, text="取消选中任务", command=self._cancel_selected_task).pack(side="left")

        self._task_cache = {}  # book_id -> (pct, stage, title)

    # ---------- 设置页 ----------
    def _build_settings_page(self):
        frm = ttk.Frame(self.page_settings, padding=16)
        frm.pack(fill="both", expand=True)
        pad = {"padx": 10, "pady": 7}

        ttk.Label(frm, text="输出目录").grid(row=0, column=0, sticky="w", **pad)
        self.out_dir_var = tk.StringVar(value=self.config.get("output_dir"))
        ttk.Entry(frm, textvariable=self.out_dir_var, width=52).grid(
            row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="浏览…", command=self._browse_out_dir).grid(
            row=0, column=2, **pad)

        ttk.Label(frm, text="同时下载书籍数").grid(row=1, column=0, sticky="w", **pad)
        self.conc_var = tk.StringVar(value=str(self.config.get("concurrency")))
        ttk.Spinbox(frm, from_=1, to=10, textvariable=self.conc_var, width=10).grid(
            row=1, column=1, sticky="w", **pad)

        ttk.Label(frm, text="书内章节并发数").grid(row=2, column=0, sticky="w", **pad)
        self.pool_var = tk.StringVar(value=str(self.config.get("chapter_pool")))
        ttk.Spinbox(frm, from_=1, to=8, textvariable=self.pool_var, width=10).grid(
            row=2, column=1, sticky="w", **pad)

        ttk.Label(frm, text="请求超时（秒）").grid(row=3, column=0, sticky="w", **pad)
        self.timeout_var = tk.StringVar(value=str(self.config.get("timeout")))
        ttk.Spinbox(frm, from_=5, to=60, textvariable=self.timeout_var, width=10).grid(
            row=3, column=1, sticky="w", **pad)

        ttk.Label(frm, text="失败重试次数").grid(row=4, column=0, sticky="w", **pad)
        self.retry_var = tk.StringVar(value=str(self.config.get("retries")))
        ttk.Spinbox(frm, from_=0, to=6, textvariable=self.retry_var, width=10).grid(
            row=4, column=1, sticky="w", **pad)

        ttk.Label(frm, text="章节请求间隔（秒）").grid(row=5, column=0, sticky="w", **pad)
        self.delay_var = tk.StringVar(value=str(self.config.get("delay")))
        ttk.Spinbox(frm, from_=0, to=5, increment=0.1, textvariable=self.delay_var,
                    width=10).grid(row=5, column=1, sticky="w", **pad)

        ttk.Button(frm, text="保存设置", command=self._save_settings).grid(
            row=6, column=1, sticky="w", **pad)

        ttk.Label(frm, text="注意：本工具用于阅读捕获并整理**非版权（公版）作品**。"
                            "请遵守目标网站的访问规则与当地法律。",
                  foreground="#a55", wraplength=560).grid(
            row=7, column=0, columnspan=3, sticky="w", **pad)

        frm.columnconfigure(1, weight=1)

    # ---------- 事件轮询 ----------
    def _poll_events(self):
        try:
            while True:
                evt, payload = self.manager.events.get_nowait()
                self._handle_event(evt, payload)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def _handle_event(self, evt, payload):
        if evt == "book_added":
            self._log(f"已加入队列：{payload['title'] or '未命名'}")
        elif evt == "status":
            if payload["status"] == "running":
                self._log(f"开始下载：{payload['book_id']}")
            self.refresh_library()
            self.refresh_tasks()
        elif evt == "progress":
            bid = payload["book_id"]
            self._task_cache[bid] = (payload["pct"], payload["msg"], payload["title"])
            self.refresh_tasks()
            self.status_var.set(f"{payload['title'] or '书籍'}：{payload['msg']} {payload['pct']:.0f}%")
        elif evt == "book_done":
            p = payload
            self._log(f"✔ 完成《{p['title']}》{p['chapters']} 章，"
                      f"{utils.format_word_count(p['words'])} 字 → {p['txt_path']}")
            self._task_cache.pop(p["book_id"], None)
            self.refresh_library()
            self.refresh_tasks()
        elif evt == "book_failed":
            self._log(f"✘ 下载失败：{payload['error']}")
            self._task_cache.pop(payload["book_id"], None)
            self.refresh_library()
            self.refresh_tasks()

    # ---------- 操作 ----------
    def _open_output_dir(self):
        out = self.config.get("output_dir")
        os.makedirs(out, exist_ok=True)
        os.startfile(out)

    def _selected_book(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(self.tree.item(sel[0], "values")[0])

    def _read_selected(self):
        """双击书籍 → 打开内置阅读器。"""
        bid = self._selected_book()
        if bid is None:
            return
        book = self.db.get_book(bid)
        if not book:
            return
        ReaderWindow(self, book)

    def _open_selected(self, kind):
        bid = self._selected_book()
        if bid is None:
            messagebox.showinfo("提示", "请先在列表中选择一本书")
            return
        book = self.db.get_book(bid)
        if not book:
            return
        path = book.get("epub_path") if kind == "epub" else book.get("txt_path")
        if not path or not os.path.exists(path):
            messagebox.showinfo("提示", "该书籍尚未生成此格式文件")
            return
        os.startfile(path)

    def _redownload_selected(self):
        bid = self._selected_book()
        if bid is None:
            return
        book = self.db.get_book(bid)
        if not book:
            return
        if not messagebox.askyesno("重新下载", f"重新下载《{book['title']}》？"):
            return
        seeds = book.get("source_seeds") or "[]"
        import json
        try:
            seeds = json.loads(seeds)
        except Exception:
            seeds = []
        try:
            self.manager.add_download(book["title"], book["author"], seeds)
        except ValueError as e:
            messagebox.showerror("错误", str(e))

    def _delete_selected(self):
        bid = self._selected_book()
        if bid is None:
            messagebox.showinfo("提示", "请先在书籍列表中选中要删除的书籍")
            return
        book = self.db.get_book(bid)
        if not book:
            return
        if not messagebox.askyesno("删除记录",
                                   f"删除《{book['title']}》的下载记录？\n（输出文件不会被删除）"):
            return
        self.db.delete_book(bid)
        self.refresh_library()

    def _popup_lib_menu(self, event):
        """右键菜单：先选中光标所在行，再弹出操作菜单。"""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        try:
            self._lib_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._lib_menu.grab_release()

    def _cancel_selected_task(self):
        if not hasattr(self, "task_tree"):
            return
        sel = self.task_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在任务列表中选择任务")
            return
        book_id = int(sel[0])
        self.manager.cancel(book_id)
        self._log(f"已请求取消任务 #{book_id}")

    def _browse_out_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_dir_var.get())
        if d:
            self.out_dir_var.set(d)

    def _save_settings(self):
        try:
            self.config.set("output_dir", self.out_dir_var.get().strip())
            self.config.set("concurrency", int(self.conc_var.get()))
            self.config.set("chapter_pool", int(self.pool_var.get()))
            self.config.set("timeout", int(self.timeout_var.get()))
            self.config.set("retries", int(self.retry_var.get()))
            self.config.set("delay", float(self.delay_var.get()))
        except ValueError:
            messagebox.showerror("错误", "设置数值格式不正确")
            return
        # 重新创建管理器以应用并发数
        self.manager.shutdown()
        self.manager = DownloadManager(self.db, self.config, logger=self._log)
        messagebox.showinfo("已保存", "设置已保存并生效")

    # ---------- 刷新 ----------
    def refresh_library(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for b in self.db.list_books():
            self.tree.insert("", "end", iid=str(b["id"]), values=(
                b["id"], b["title"] or "未命名", b["author"] or "佚名",
                b["chapters_fetched"] or 0, utils.format_word_count(b["word_count"]),
                STATUS_TEXT.get(b["status"], b["status"]), b["updated_at"]))

    def refresh_tasks(self):
        if not hasattr(self, "task_tree"):
            return
        for i in self.task_tree.get_children():
            self.task_tree.delete(i)
        running = self.db.list_books()
        cur = None
        for b in running:
            if b["status"] not in ("queued", "running"):
                continue
            pct, stage, title = self._task_cache.get(b["id"], (0, "排队中", b["title"]))
            iid = str(b["id"])
            self.task_tree.insert("", "end", iid=iid, values=(
                title or b["title"], f"{pct:.0f}%", stage))
            if cur is None:
                cur = iid
        if cur:
            self.task_tree.selection_set(cur)
            pct, stage, _ = self._task_cache.get(int(cur), (0, "", ""))
            self.progress["value"] = pct
        else:
            self.progress["value"] = 0

    # ---------- 日志 ----------
    def _log(self, msg: str):
        def _do():
            if hasattr(self, "log_text") and self.log_text.winfo_exists():
                self.log_text.config(state="normal")
                self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
            elif hasattr(self, "status_var"):
                try:
                    self.status_var.set(msg[:80])
                except Exception:
                    pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def _on_close(self):
        self.manager.shutdown()
        self.root.destroy()


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
