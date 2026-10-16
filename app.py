# -*- coding: utf-8 -*-
"""TXT_Catcher 桌面应用入口：可视化管理下载任务与书籍库。

运行：python app.py  （或双击 run.bat / 使用打包后的 exe）
"""
import ctypes
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
from novel_catcher import utils

APP_TITLE = "TXT_Catcher 公版小说抓取器"
FONT = "Microsoft YaHei UI"

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


class AddDialog(tk.Toplevel):
    """新建下载对话框：书名/作者/章节网址 + 章节预览。"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("新建下载")
        self.geometry("640x560")
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()

        pad = {"padx": 12, "pady": 6}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="书名（留空则自动取首个页面标题）").grid(row=0, column=0, sticky="w", **pad)
        self.title_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="作者（可选）").grid(row=1, column=0, sticky="w", **pad)
        self.author_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.author_var).grid(row=1, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="章节网址（提供其中几章即可，每行一个）").grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)
        self.urls_text = tk.Text(frm, width=72, height=14, font=(FONT, 10))
        self.urls_text.grid(row=3, column=0, columnspan=2, sticky="nsew", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        self.preview_btn = ttk.Button(btns, text="预览章节位置", command=self.preview)
        self.preview_btn.pack(side="left", padx=(0, 8))
        self.ok_btn = ttk.Button(btns, text="开始下载", command=self.start)
        self.ok_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btns, text="关闭", command=self.destroy)
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.preview_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.preview_var, foreground="#0a6", wraplength=580).grid(
            row=5, column=0, columnspan=2, sticky="w", **pad)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)
        self._preview_result = []

    def _seeds(self):
        urls = []
        for line in self.urls_text.get("1.0", "end").splitlines():
            u = utils.normalize_url(line)
            if u:
                urls.append(u)
        return urls

    def preview(self):
        seeds = self._seeds()
        if not seeds:
            messagebox.showwarning("提示", "请先粘贴至少一个章节网址", parent=self)
            return
        self.preview_btn.config(state="disabled")
        self.preview_var.set("正在分析章节位置…")
        self._preview_result = []
        cfg = self.app.config

        def work():
            try:
                fetcher = HttpFetcher(cfg)
                urls = discover.discover_chapters(
                    fetcher, seeds, max_chapters=cfg.get("max_chapters"))
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
        self.preview_btn.config(state="normal")
        if err:
            self.preview_var.set(f"分析失败：{err}")
            return
        shown = "、".join(urls[:3])
        more = f"… 共 {len(urls)} 章" if len(urls) > 3 else ""
        self.preview_var.set(f"已定位 {len(urls)} 个章节：{shown}{more}")
        self.app.preview_count = len(urls)

    def start(self):
        seeds = self._seeds()
        if not seeds:
            messagebox.showwarning("提示", "请先粘贴至少一个章节网址", parent=self)
            return
        try:
            book_id = self.app.manager.add_download(
                self.title_var.get().strip(), self.author_var.get().strip(), seeds)
            self.app.refresh_library()
            self.destroy()
        except ValueError as e:
            messagebox.showerror("错误", str(e), parent=self)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = Config()
        from novel_catcher.config import DEFAULT_DB_PATH
        self.db = DB(DEFAULT_DB_PATH)
        self.manager = DownloadManager(self.db, self.config, logger=self._log)
        self.preview_count = 0
        self._build_ui()
        self._poll_events()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 界面 ----------
    def _build_ui(self):
        self.root.title(APP_TITLE)
        self.root.geometry("960x640")
        self.root.minsize(860, 560)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Treeview", rowheight=26, font=(FONT, 10))
        style.configure("Treeview.Heading", font=(FONT, 10, "bold"))
        style.configure("TNotebook.Tab", font=(FONT, 10))
        style.configure("TButton", font=(FONT, 10))
        style.configure("TLabel", font=(FONT, 10))
        style.configure("TLabelframe.Label", font=(FONT, 10))

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_library = ttk.Frame(nb)
        self.tab_tasks = ttk.Frame(nb)
        self.tab_settings = ttk.Frame(nb)
        nb.add(self.tab_library, text="  书籍库  ")
        nb.add(self.tab_tasks, text="  下载任务  ")
        nb.add(self.tab_settings, text="  设置  ")

        self._build_library_tab()
        self._build_tasks_tab()
        self._build_settings_tab()

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                  font=(FONT, 9)).pack(fill="x", padx=10, pady=(0, 6))

        self.refresh_library()
        self.refresh_tasks()

    def _build_library_tab(self):
        frm = ttk.Frame(self.tab_library, padding=8)
        frm.pack(fill="both", expand=True)

        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="＋ 新建下载", command=self._open_add_dialog).pack(side="left")
        ttk.Button(bar, text="刷新", command=self.refresh_library).pack(side="left", padx=6)
        ttk.Button(bar, text="打开输出目录", command=self._open_output_dir).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="打开TXT", command=lambda: self._open_selected("txt")).pack(side="left")
        ttk.Button(bar, text="打开EPUB", command=lambda: self._open_selected("epub")).pack(side="left", padx=6)
        ttk.Button(bar, text="重新下载", command=self._redownload_selected).pack(side="left")
        ttk.Button(bar, text="删除记录", command=self._delete_selected).pack(side="left", padx=(6, 0))

        cols = ("id", "title", "author", "chapters", "words", "status", "time")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        heads = {"id": ("ID", 44), "title": ("书名", 240), "author": ("作者", 110),
                 "chapters": ("章节", 64), "words": ("字数", 90),
                 "status": ("状态", 90), "time": ("更新时间", 140)}
        for c, (t, w) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c != "title" else "w")
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._open_selected("txt"))

    def _build_tasks_tab(self):
        frm = ttk.Frame(self.tab_tasks, padding=8)
        frm.pack(fill="both", expand=True)

        self.task_tree = ttk.Treeview(frm, columns=("title", "pct", "stage"),
                                      show="headings", selectmode="browse", height=6)
        self.task_tree.heading("title", text="书名")
        self.task_tree.heading("pct", text="进度")
        self.task_tree.heading("stage", text="阶段")
        self.task_tree.column("title", width=300)
        self.task_tree.column("pct", width=90, anchor="center")
        self.task_tree.column("stage", width=330)
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

    def _build_settings_tab(self):
        frm = ttk.Frame(self.tab_settings, padding=12)
        frm.pack(fill="both", expand=True)
        pad = {"padx": 10, "pady": 6}

        ttk.Label(frm, text="输出目录").grid(row=0, column=0, sticky="w", **pad)
        self.out_dir_var = tk.StringVar(value=self.config.get("output_dir"))
        ttk.Entry(frm, textvariable=self.out_dir_var, width=50).grid(
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

        ttk.Label(frm, text="注意：本工具仅用于抓取**非版权（公版）作品**。"
                            "请遵守目标网站的访问规则与当地法律。",
                  foreground="#a55", wraplength=520).grid(
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
    def _open_add_dialog(self):
        AddDialog(self)

    def _open_output_dir(self):
        out = self.config.get("output_dir")
        os.makedirs(out, exist_ok=True)
        os.startfile(out)

    def _selected_book(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(self.tree.item(sel[0], "values")[0])

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
            return
        book = self.db.get_book(bid)
        if not book:
            return
        if not messagebox.askyesno("删除记录",
                                   f"删除《{book['title']}》的下载记录？\n（输出文件不会被删除）"):
            return
        self.db.delete_book(bid)
        self.refresh_library()

    def _cancel_selected_task(self):
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
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
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
