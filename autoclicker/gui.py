"""tkinter 图形界面：把“改代码调坐标”变成“点几下鼠标”。

界面分区：
1. 工具栏       —— 新建 / 打开 / 保存 配置
2. 步骤列表     —— 增删改、上下移动、复制
3. 任务设置     —— 循环、倒计时、目标窗口、抖动、空跑等
4. 运行控制     —— 开始 / 暂停 / 停止，实时状态
5. 日志面板     —— 彩色分级输出

两个屏幕拾取器（替代原来的三条 Python 小脚本）：
- **坐标拾取**：半透明全屏浮层跟随鼠标显示坐标，空格或点击即锁定
- **区域截图**：全屏拖拽框选，自动生成模板图片，供“等待图片”步骤使用
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import uuid
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from . import profile as pm
from .engine import Engine
from .platform_adapter import (
    DependencyStatus,
    Grabber,
    WindowTools,
    resource_path,
)

# 热键依赖是可选的：Linux 未以 root 运行时 keyboard 会失效，此时降级为仅按钮控制
try:
    import keyboard as _keyboard
except Exception:
    _keyboard = None

ACCENT = "#3b6fd4"
LOG_COLORS = {"info": "#222222", "warn": "#b8860b", "error": "#c0392b", "success": "#1e8449"}


# --------------------------------------------------------------------------- 拾取器

class CoordinatePicker(tk.Toplevel):
    """半透明全屏浮层：跟随鼠标显示坐标，空格 / 单击锁定，Esc 取消。"""

    def __init__(self, master, initial_hint: str = "") -> None:
        super().__init__(master)
        self.result: Optional[tuple] = None
        self.grabber = Grabber()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.28)
        except Exception:
            pass
        self.configure(bg="#0b1d3a", cursor="crosshair")
        self.geometry(self._virtual_geometry())

        self.canvas = tk.Canvas(self, bg="#0b1d3a", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.create_text(
            self.winfo_screenwidth() // 2, 46,
            text="移动鼠标到目标位置 —— 按【空格】或单击锁定，【Esc】取消",
            fill="#ffffff", font=("Microsoft YaHei", 16, "bold"), tags=("hint",),
        )
        if initial_hint:
            self.canvas.create_text(
                self.winfo_screenwidth() // 2, 78,
                text=initial_hint, fill="#ffd479", font=("Microsoft YaHei", 12), tags=("hint",),
            )

        # 十字线 + 坐标标签，随鼠标移动
        self.cross_v = self.canvas.create_line(0, 0, 0, 0, fill="#ff4d4f", width=1)
        self.cross_h = self.canvas.create_line(0, 0, 0, 0, fill="#ff4d4f", width=1)
        self.label_bg = self.canvas.create_rectangle(0, 0, 0, 0, fill="#111827", outline="#ff4d4f")
        self.label = self.canvas.create_text(0, 0, text="", fill="#ffffff",
                                             font=("Consolas", 12, "bold"))

        self.bind("<Motion>", self._on_motion)
        self.bind("<Button-1>", lambda e: self._capture())
        self.bind("<KeyPress-space>", lambda e: self._capture())
        self.bind("<KeyPress-Escape>", lambda e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.focus_force()
        self.grab_set()
        self._tick()

    def _virtual_geometry(self) -> str:
        """覆盖整个虚拟桌面（多显示器时可能带负坐标）。"""
        g = Grabber()
        try:
            img, (ox, oy) = g.grab()
            scale = g.measure_scale()
            return f"{int(img.width / scale)}x{int(img.height / scale)}+{ox}+{oy}"
        except Exception:
            return f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0"

    def _on_motion(self, event=None) -> None:
        # 统一以屏幕实际指针为准，避免轮询时用伪造事件覆盖真实坐标
        px, py = self.winfo_pointerxy()
        self._last = (px, py)
        w, h = 120, 26
        self.canvas.coords(self.cross_v, x, 0, x, self.winfo_screenheight())
        self.canvas.coords(self.cross_h, 0, y, self.winfo_screenwidth(), y)
        lx, ly = x + 14, y + 14
        if lx + w > self.winfo_screenwidth():
            lx = x - w - 14
        if ly + h > self.winfo_screenheight():
            ly = y - h - 14
        self.canvas.coords(self.label_bg, lx, ly, lx + w, ly + h)
        self.canvas.coords(self.label, lx + w / 2, ly + h / 2)
        self.canvas.itemconfig(self.label, text=f"{self._last[0]}, {self._last[1]}")

    def _tick(self) -> None:
        """不依赖鼠标事件也能刷新坐标（浮层挡不住底层窗口时使用场景）。"""
        if self.winfo_exists():
            try:
                self._on_motion()
            except Exception:
                pass
            self.after(80, self._tick)

    def _capture(self) -> None:
        try:
            import pyautogui as pag

            self.result = tuple(pag.position())
        except Exception:
            self.result = getattr(self, "_last", None)
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class RegionCapture(tk.Toplevel):
    """全屏拖拽框选区域并存为模板图片。"""

    def __init__(self, master, save_dir: str) -> None:
        super().__init__(master)
        self.result: Optional[str] = None
        self.save_dir = save_dir
        self.start = None
        self.rect = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.35)
        except Exception:
            pass
        self.configure(bg="#000000", cursor="crosshair")
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            self.winfo_screenwidth() // 2, 40,
            text="按住鼠标左键拖出方框选择按钮区域，松开完成截图，【Esc】取消",
            fill="#ffffff", font=("Microsoft YaHei", 14, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.bind("<KeyPress-Escape>", lambda e: self._close())
        self.focus_force()
        self.grab_set()

    def _down(self, event) -> None:
        self.start = (event.x, event.y)
        self.rect = self.canvas.create_rectangle(*self.start, *self.start,
                                                 outline="#ff4d4f", width=2)

    def _move(self, event) -> None:
        self.canvas.coords(self.rect, self.start[0], self.start[1], event.x, event.y)

    def _up(self, event) -> None:
        try:
            self.canvas.coords(self.rect, self.start[0], self.start[1], event.x, event.y)
            self.update()
            x1, y1 = min(self.start[0], event.x), min(self.start[1], event.y)
            x2, y2 = max(self.start[0], event.x), max(self.start[1], event.y)
            if x2 - x1 < 4 or y2 - y1 < 4:
                self._close()
                return
            self.withdraw()  # 关键：截图前必须收起浮层，否则把浮层一起拍进去
            self.after(120)
            self.update()

            g = Grabber()
            scale = g.measure_scale()
            img, (ox, oy) = g.grab()
            box = (int((ox + x1) * scale), int((oy + y1) * scale),
                   int((ox + x2) * scale), int((oy + y2) * scale))
            crop = img.crop(box)
            os.makedirs(self.save_dir, exist_ok=True)
            name = f"template_{uuid.uuid4().hex[:6]}.png"
            path = os.path.join(self.save_dir, name)
            crop.save(path)
            self.result = path
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# --------------------------------------------------------------------------- 步骤编辑
class StepDialog(tk.Toplevel):
    """单个步骤的编辑框，全部控件由 profile.Step 的字段驱动。"""

    def __init__(self, master, step: pm.Step, templates_dir: str) -> None:
        super().__init__(master)
        self.step = step
        self.templates_dir = templates_dir
        self.ok = False
        self.title("编辑步骤" if step.name or step.kind else "新增步骤")
        self.transient(master)
        self.resizable(False, False)
        self._build()
        self.grab_set()
        self.wait_window(self)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 5}
        row = 0
        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0)

        ttk.Label(frm, text="名称").grid(row=row, column=0, sticky="e", **pad)
        self.v_name = tk.StringVar(value=self.step.name)
        ttk.Entry(frm, textvariable=self.v_name, width=34).grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1

        ttk.Label(frm, text="类型").grid(row=row, column=0, sticky="e", **pad)
        self.v_kind = tk.StringVar(value=self.step.kind)
        kinds = ttk.Combobox(frm, textvariable=self.v_kind, width=18, state="readonly",
                             values=list(pm.STEP_KINDS.keys()))
        kinds.grid(row=row, column=1, sticky="w", **pad)
        kinds.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        row += 1

        self.pos_frame = ttk.LabelFrame(frm, text="坐标")
        self.pos_frame.grid(row=row, column=0, columnspan=3, sticky="we", **pad)
        self.v_x = tk.IntVar(value=self.step.x)
        self.v_y = tk.IntVar(value=self.step.y)
        self.v_mode = tk.StringVar(value=self.step.coord_mode)
        ttk.Label(self.pos_frame, text="X").grid(row=0, column=0, **pad)
        ttk.Entry(self.pos_frame, textvariable=self.v_x, width=8).grid(row=0, column=1, **pad)
        ttk.Label(self.pos_frame, text="Y").grid(row=0, column=2, **pad)
        ttk.Entry(self.pos_frame, textvariable=self.v_y, width=8).grid(row=0, column=3, **pad)
        ttk.Button(self.pos_frame, text="拾取坐标", command=self._pick).grid(row=0, column=4, **pad)
        ttk.Radiobutton(self.pos_frame, text="绝对坐标", value=pm.CoordModeAbsolute,
                        variable=self.v_mode).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Radiobutton(self.pos_frame, text="相对目标窗口", value=pm.CoordModeWindow,
                        variable=self.v_mode).grid(row=1, column=2, columnspan=3, sticky="w", **pad)
        row += 1

        self.key_frame = ttk.LabelFrame(frm, text="按键 / 文本 / 滚动")
        self.key_frame.grid(row=row, column=0, columnspan=3, sticky="we", **pad)
        ttk.Label(self.key_frame, text="组合键").grid(row=0, column=0, **pad)
        self.v_keys = tk.StringVar(value=self.step.keys)
        ttk.Entry(self.key_frame, textvariable=self.v_keys, width=16).grid(row=0, column=1, **pad)
        ttk.Label(self.key_frame, text="如 end / ctrl+s").grid(row=0, column=2, sticky="w", **pad)
        ttk.Label(self.key_frame, text="文本").grid(row=1, column=0, **pad)
        self.v_text = tk.StringVar(value=self.step.text)
        ttk.Entry(self.key_frame, textvariable=self.v_text, width=30).grid(row=1, column=1, columnspan=2, **pad)
        ttk.Label(self.key_frame, text="滚动量").grid(row=2, column=0, **pad)
        self.v_scroll = tk.IntVar(value=self.step.scroll)
        ttk.Entry(self.key_frame, textvariable=self.v_scroll, width=8).grid(row=2, column=1, **pad)
        row += 1

        self.img_frame = ttk.LabelFrame(frm, text="模板图片（任一命中即可）")
        self.img_frame.grid(row=row, column=0, columnspan=3, sticky="we", **pad)
        self.lb_images = tk.Listbox(self.img_frame, height=3, width=46)
        self.lb_images.grid(row=0, column=0, columnspan=3, **pad)
        for p in self.step.images:
            self.lb_images.insert("end", p)
        ttk.Button(self.img_frame, text="选择图片", command=self._choose_image).grid(row=1, column=0, **pad)
        ttk.Button(self.img_frame, text="屏幕框选", command=self._capture_image).grid(row=1, column=1, **pad)
        ttk.Button(self.img_frame, text="移除", command=self._remove_image).grid(row=1, column=2, **pad)
        ttk.Label(self.img_frame, text="相似度").grid(row=2, column=0, **pad)
        self.v_conf = tk.DoubleVar(value=self.step.confidence)
        ttk.Spinbox(self.img_frame, from_=0.3, to=1.0, increment=0.05,
                    textvariable=self.v_conf, width=6).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(self.img_frame, text="超时(s)").grid(row=2, column=2, **pad)
        self.v_timeout = tk.DoubleVar(value=self.step.timeout)
        ttk.Spinbox(self.img_frame, from_=0.5, to=120, increment=0.5,
                    textvariable=self.v_timeout, width=6).grid(row=2, column=3, sticky="w", **pad)
        row += 1

        time_frame = ttk.LabelFrame(frm, text="节奏")
        time_frame.grid(row=row, column=0, columnspan=3, sticky="we", **pad)
        self.v_before = tk.DoubleVar(value=self.step.delay_before)
        self.v_after = tk.DoubleVar(value=self.step.delay_after)
        self.v_jitter = tk.DoubleVar(value=self.step.jitter)
        for i, (txt, var, lo, hi) in enumerate(
                [("前置等待(s)", self.v_before, 0, 60), ("后置等待(s)", self.v_after, 0, 60),
                 ("随机抖动(s)", self.v_jitter, 0, 5)]):
            ttk.Label(time_frame, text=txt).grid(row=0, column=i * 2, **pad)
            ttk.Spinbox(time_frame, from_=lo, to=hi, increment=0.1, textvariable=var,
                        width=7).grid(row=0, column=i * 2 + 1, **pad)
        row += 1

        self.v_enabled = tk.BooleanVar(value=self.step.enabled)
        ttk.Checkbutton(frm, text="启用该步骤", variable=self.v_enabled).grid(row=row, column=1, sticky="w", **pad)
        self.v_optional = tk.BooleanVar(value=self.step.optional)
        self.cb_optional = ttk.Checkbutton(frm, text="图片找不到时不报错（跳过）",
                                           variable=self.v_optional)
        self.cb_optional.grid(row=row, column=2, sticky="w", **pad)
        row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=3, pady=(12, 2))
        ttk.Button(btns, text="确定", command=self._ok).pack(side="right", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=6)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self._refresh()

    def _refresh(self) -> None:
        kind = self.v_kind.get()
        pos_ok = kind in ("click", "double_click", "right_click", "move")
        key_ok = kind in ("key", "text", "scroll")
        img_ok = kind in ("wait_image",)

        def set_state(frame, enabled):
            for child in frame.winfo_children():
                try:
                    child.configure(state="normal" if enabled else "disabled")
                except Exception:
                    pass  # 部分控件不支持 state，忽略即可

        set_state(self.pos_frame, pos_ok)
        set_state(self.key_frame, key_ok)
        set_state(self.img_frame, img_ok)

    def _pick(self) -> None:
        self.iconify()
        picker = CoordinatePicker(self.master)
        self.wait_window(picker)
        self.deiconify()
        if picker.result:
            self.v_x.set(picker.result[0])
            self.v_y.set(picker.result[1])

    def _choose_image(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self, title="选择模板图片",
            initialdir=os.path.abspath(self.templates_dir) if os.path.isdir(self.templates_dir) else ".",
            filetypes=[("图片", "*.png;*.jpg;*.jpeg;*.bmp"), ("所有文件", "*.*")])
        for p in paths:
            self.lb_images.insert("end", p)

    def _capture_image(self) -> None:
        self.iconify()
        cap = RegionCapture(self.master, self.templates_dir)
        self.wait_window(cap)
        self.deiconify()
        if cap.result:
            self.lb_images.insert("end", cap.result)

    def _remove_image(self) -> None:
        sel = self.lb_images.curselection()
        for i in reversed(sel):
            self.lb_images.delete(i)

    def _ok(self) -> None:
        try:
            self.step.name = self.v_name.get().strip()
            self.step.kind = self.v_kind.get()
            self.step.x = int(self.v_x.get())
            self.step.y = int(self.v_y.get())
            self.step.coord_mode = self.v_mode.get()
            self.step.keys = self.v_keys.get().strip()
            self.step.text = self.v_text.get()
            self.step.scroll = int(self.v_scroll.get())
            self.step.images = list(self.lb_images.get(0, "end"))
            self.step.confidence = float(self.v_conf.get())
            self.step.timeout = float(self.v_timeout.get())
            self.step.delay_before = float(self.v_before.get())
            self.step.delay_after = float(self.v_after.get())
            self.step.jitter = float(self.v_jitter.get())
            self.step.enabled = bool(self.v_enabled.get())
            self.step.optional = bool(self.v_optional.get())
        except Exception as exc:
            messagebox.showerror("输入有误", str(exc), parent=self)
            return
        self.ok = True
        self.destroy()


# --------------------------------------------------------------------------- 主界面
class App:
    """主窗口。"""

    def __init__(self, root: tk.Tk, profile_path: Optional[str] = None) -> None:
        self.root = root
        self.root.title("自动点击器 Auto Clicker · 可视化配置")
        self.root.geometry("1000x680")
        self.root.minsize(900, 620)

        self.profile = pm.Profile()
        self.current_path: Optional[str] = profile_path
        self.engine: Optional[Engine] = None
        self.log_queue: "queue.Queue" = queue.Queue()
        self.templates_dir = resource_path("templates")
        self.profiles_dir = resource_path("profiles")

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self._build_ui()
        self._poll_log()

        if profile_path and os.path.exists(profile_path):
            self._load_into(profile_path)
        else:
            self.profile = pm.example_profile()
            self._refresh_steps()

        self._register_hotkeys()

    # ---------------------------------------------------------------- 构建
    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Button(top, text="新建", command=self._new_profile).pack(side="left", padx=3)
        ttk.Button(top, text="打开…", command=self._open_profile).pack(side="left", padx=3)
        ttk.Button(top, text="保存", command=self._save_profile).pack(side="left", padx=3)
        ttk.Button(top, text="另存为…", command=self._save_as).pack(side="left", padx=3)
        ttk.Button(top, text="载入示例", command=self._load_example).pack(side="left", padx=3)

        self.lbl_file = ttk.Label(top, text="未保存", foreground="#666666")
        self.lbl_file.pack(side="right", padx=8)

        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=4)

        left = ttk.Frame(body)
        body.add(left, weight=3)

        cols = ("no", "enabled", "kind", "desc")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=14)
        headers = {"no": "#", "enabled": "启用", "kind": "类型", "desc": "说明"}
        widths = {"no": 40, "enabled": 50, "kind": 90, "desc": 320}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center" if c != "desc" else "w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit_step())
        self.tree.bind("<Delete>", lambda e: self._delete_step())

        bar = ttk.Frame(left, padding=(0, 6))
        bar.pack(fill="x")
        for txt, cmd in [("新增", self._add_step), ("编辑", self._edit_step),
                         ("复制", self._duplicate_step), ("删除", self._delete_step),
                         ("上移", lambda: self._move(-1)), ("下移", lambda: self._move(1))]:
            ttk.Button(bar, text=txt, command=cmd).pack(side="left", padx=2)

        right = ttk.Frame(body, padding=(6, 0))
        body.add(right, weight=2)
        self._build_settings(right)
        self._build_runner(right)
        self._build_log(right)

    def _build_settings(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="任务设置", padding=8)
        box.pack(fill="x", pady=(0, 8))

        self.v_name = tk.StringVar()
        self.v_loop = tk.BooleanVar(value=True)
        self.v_loop_count = tk.IntVar(value=1)
        self.v_countdown = tk.DoubleVar(value=3.0)
        self.v_target = tk.StringVar()
        self.v_require = tk.BooleanVar(value=False)
        self.v_failsafe = tk.BooleanVar(value=True)
        self.v_jitter = tk.DoubleVar(value=0.0)
        self.v_interval = tk.DoubleVar(value=0.05)
        self.v_dry = tk.BooleanVar(value=False)

        r = 0
        ttk.Label(box, text="任务名").grid(row=r, column=0, sticky="e", pady=3)
        ttk.Entry(box, textvariable=self.v_name, width=26).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Checkbutton(box, text="循环执行", variable=self.v_loop,
                        command=self._toggle_loop).grid(row=r, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.v_loop_count, width=6).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(box, text="开始倒计时(s)").grid(row=r, column=0, sticky="e")
        ttk.Spinbox(box, from_=0, to=30, increment=0.5, textvariable=self.v_countdown,
                    width=6).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(box, text="目标窗口标题").grid(row=r, column=0, sticky="e")
        ttk.Entry(box, textvariable=self.v_target, width=26).grid(row=r, column=1, sticky="w")
        ttk.Button(box, text="取当前", command=self._capture_active_window).grid(row=r, column=2, padx=4)
        r += 1
        ttk.Checkbutton(box, text="窗口不在前台时等待", variable=self.v_require).grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        ttk.Checkbutton(box, text="左上角急停（推荐）", variable=self.v_failsafe).grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        ttk.Checkbutton(box, text="空跑（只记录不操作）", variable=self.v_dry).grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        ttk.Label(box, text="随机抖动(s)").grid(row=r, column=0, sticky="e")
        ttk.Spinbox(box, from_=0, to=5, increment=0.1, textvariable=self.v_jitter,
                    width=6).grid(row=r, column=1, sticky="w")
        ttk.Label(box, text="动作间隔(s)").grid(row=r, column=2, sticky="e")
        ttk.Spinbox(box, from_=0, to=3, increment=0.05, textvariable=self.v_interval,
                    width=6).grid(row=r + 1, column=2, sticky="w")

    def _build_runner(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="运行控制", padding=8)
        box.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x")
        self.btn_start = ttk.Button(row, text="▶ 开始 (F9)", command=self._start)
        self.btn_start.pack(side="left", padx=3)
        self.btn_pause = ttk.Button(row, text="⏸ 暂停", command=self._pause, state="disabled")
        self.btn_pause.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(row, text="■ 停止 (F10)", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=3)

        self.lbl_status = ttk.Label(box, text="就绪", foreground=ACCENT,
                                    font=("Microsoft YaHei", 10, "bold"))
        self.lbl_status.pack(anchor="w", pady=(6, 0))

        env = DependencyStatus()
        note = env.human_readable()
        ttk.Label(box, text=f"环境：{DependencyStatus.report()['system']} · {note}",
                  foreground="#666666", wraplength=430, justify="left").pack(anchor="w")

    def _build_log(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="运行日志", padding=6)
        box.pack(fill="both", expand=True)
        self.txt_log = tk.Text(box, height=12, wrap="word", font=("Consolas", 9))
        scroll = ttk.Scrollbar(box, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.txt_log.pack(fill="both", expand=True)
        for level, color in LOG_COLORS.items():
            self.txt_log.tag_config(level, foreground=color)

    # ---------------------------------------------------------------- 数据同步
    def _sync_from_ui(self) -> None:
        self.profile.name = self.v_name.get().strip() or "未命名任务"
        st = self.profile.settings
        st.loop = bool(self.v_loop.get())
        st.loop_count = int(self.v_loop_count.get())
        st.countdown = float(self.v_countdown.get())
        st.target_window = self.v_target.get().strip()
        st.require_window = bool(self.v_require.get())
        st.failsafe = bool(self.v_failsafe.get())
        st.jitter = float(self.v_jitter.get())
        st.min_interval = float(self.v_interval.get())
        st.dry_run = bool(self.v_dry.get())

    def _sync_to_ui(self) -> None:
        st = self.profile.settings
        self.v_name.set(self.profile.name)
        self.v_loop.set(bool(getattr(st, "loop", True)))
        self.v_loop_count.set(int(getattr(st, "loop_count", 1)))
        self.v_countdown.set(float(getattr(st, "countdown", 3.0)))
        self.v_target.set(getattr(st, "target_window", ""))
        self.v_require.set(bool(getattr(st, "require_window", False)))
        self.v_failsafe.set(bool(getattr(st, "failsafe", True)))
        self.v_jitter.set(float(getattr(st, "jitter", 0.0)))
        self.v_interval.set(float(getattr(st, "min_interval", 0.05)))
        self.v_dry.set(bool(getattr(st, "dry_run", False)))
        self._toggle_loop()

    def _toggle_loop(self) -> None:
        try:
            self.tree  # noqa: B018 - 确保 UI 已构建
        except Exception:
            return

    def _refresh_steps(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.profile.steps, 1):
            self.tree.insert("", "end", iid=s.id,
                             values=(i, "✓" if s.enabled else "—",
                                     pm.STEP_KINDS.get(s.kind, s.kind), s.describe()))
        self._sync_to_ui()

    # ---------------------------------------------------------------- 步骤操作
    def _selected_index(self) -> Optional[int]:
        sel = self.tree.selection()
        if not sel:
            return None
        sid = sel[0]
        for i, s in enumerate(self.profile.steps):
            if s.id == sid:
                return i
        return None

    def _add_step(self) -> None:
        dlg = StepDialog(self.root, pm.Step(), self.templates_dir)
        if dlg.ok:
            self.profile.steps.append(dlg.step)
            self._refresh_steps()

    def _edit_step(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        step = self.profile.steps[idx]
        snapshot = pm.Step(**step.__dict__.copy())
        dlg = StepDialog(self.root, step, self.templates_dir)
        if not dlg.ok:
            self.profile.steps[idx] = snapshot
        self._refresh_steps()

    def _duplicate_step(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        src = self.profile.steps[idx]
        clone = pm.Step(**{k: (list(v) if isinstance(v, list) else v)
                           for k, v in src.__dict__.items() if k != "id"})
        clone.id = uuid.uuid4().hex[:8]
        self.profile.steps.insert(idx + 1, clone)
        self._refresh_steps()

    def _delete_step(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        del self.profile.steps[idx]
        self._refresh_steps()

    def _move(self, delta: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new = idx + delta
        if not (0 <= new < len(self.profile.steps)):
            return
        self.profile.steps[idx], self.profile.steps[new] = self.profile.steps[new], self.profile.steps[idx]
        self._refresh_steps()

    # ---------------------------------------------------------------- 文件
    def _new_profile(self) -> None:
        if not self._confirm_discard():
            return
        self.profile = pm.Profile(name="新任务")
        self.current_path = None
        self.lbl_file.config(text="未保存")
        self._refresh_steps()

    def _confirm_discard(self) -> bool:
        if not self.profile.steps:
            return True
        return messagebox.askyesno("确认", "当前配置尚未保存，确定继续？")

    def _open_profile(self) -> None:
        os.makedirs(self.profiles_dir, exist_ok=True)
        path = filedialog.askopenfilename(parent=self.root, title="打开配置",
                                          initialdir=self.profiles_dir,
                                          filetypes=[("配置文件", "*.json"), ("所有文件", "*.*")])
        if path:
            self._load_into(path)

    def _load_into(self, path: str) -> None:
        try:
            self.profile = pm.Profile.load(path)
            self.current_path = path
            self.lbl_file.config(text=os.path.basename(path))
            self._refresh_steps()
            self._log_ui(f"已载入配置：{path}", "info")
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc))

    def _load_example(self) -> None:
        if not self._confirm_discard():
            return
        self.profile = pm.example_profile()
        self.current_path = None
        self.lbl_file.config(text="未保存（示例）")
        self._refresh_steps()

    def _save_profile(self) -> None:
        if not self.current_path:
            self._save_as()
            return
        self._do_save(self.current_path)

    def _save_as(self) -> None:
        os.makedirs(self.profiles_dir, exist_ok=True)
        path = filedialog.asksaveasfilename(parent=self.root, title="保存配置",
                                            initialdir=self.profiles_dir, defextension=".json",
                                            initialvalue=(self.profile.name or "profile") + ".json",
                                            filetypes=[("配置文件", "*.json")])
        if path:
            self._do_save(path)

    def _do_save(self, path: str) -> None:
        try:
            self._sync_from_ui()
            self.profile.save(path)
            self.current_path = path
            self.lbl_file.config(text=os.path.basename(path))
            self._log_ui(f"配置已保存：{path}", "success")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    # ---------------------------------------------------------------- 运行
    def _start(self) -> None:
        if self.engine and self.engine.running:
            return
        self._sync_from_ui()
        if not self.profile.steps:
            messagebox.showinfo("提示", "还没有任何步骤，先新增几个吧")
            return
        self.engine = Engine(self.profile)
        self.engine.on_log = lambda level, msg: self.log_queue.put((level, msg))
        self.engine.on_status = lambda text: self.log_queue.put(("__status__", text))
        self.engine.start()
        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal")
        self.btn_stop.config(state="normal")

    def _pause(self) -> None:
        if self.engine:
            self.engine.toggle_pause()

    def _stop(self) -> None:
        if self.engine:
            self.engine.stop()
        self.btn_start.config(state="normal")
        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")

    def _capture_active_window(self) -> None:
        title = WindowTools().active_title()
        if title:
            self.v_target.set(title)
        else:
            messagebox.showinfo("提示", "未能读取前台窗口标题（当前平台可能不支持窗口检测）")

    # ---------------------------------------------------------------- 热键 / 日志
    def _register_hotkeys(self) -> None:
        if _keyboard is None:
            return
        try:
            _keyboard.add_hotkey("f9", lambda: self.root.after(0, self._start))
            _keyboard.add_hotkey("f10", lambda: self.root.after(0, self._stop))
        except Exception as exc:
            self._log_ui(f"热键注册失败（不影响按钮操作）：{exc}", "warn")

    def _log_ui(self, message: str, level: str = "info") -> None:
        self.log_queue.put((level, message))

    def _poll_log(self) -> None:
        try:
            while True:
                level, msg = self.log_queue.get_nowait()
                if level == "__status__":
                    self.lbl_status.config(text=msg)
                    if msg in ("已停止",):
                        self.btn_start.config(state="normal")
                        self.btn_pause.config(state="disabled")
                        self.btn_stop.config(state="disabled")
                    continue
                self.txt_log.insert("end", msg + "\n", (level,))
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)


def launch(profile_path: Optional[str] = None) -> None:
    """GUI 入口。"""
    root = tk.Tk()
    App(root, profile_path)
    root.mainloop()
