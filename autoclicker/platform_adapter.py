"""跨平台适配层：屏幕缩放 / 多显示器截图 / 窗口检测 / 依赖探测。

设计原则：**任何一项能力缺失都不能导致程序崩溃**，而是降级并在日志里说明原因，
这样同一份代码在 Windows / macOS / Linux、不同 DPI 缩放、有无 OpenCV 的环境下都能跑。

组成部分：
- ``enable_dpi_awareness()``   Windows 打开进程级 DPI 感知，消除坐标与截图的错位
- ``Grabber``                  优先用 mss 截取整个虚拟屏幕（含副屏负坐标），失败则退回 pyautogui
- ``WindowTools``              窗口枚举 / 命中检测：win32gui → pygetwindow → 不可用则返回空列表
- ``deps`` / ``locate()``      依赖探测与模板匹配，无 OpenCV 时自动退回像素级精确匹配

``WindowTools`` 提供三种取窗口的方式，供 GUI 组合使用：

- :meth:`WindowTools.active_title`   取当前前台窗口（**注意**：在按钮回调里调用只会取到本程序自己）
- :meth:`WindowTools.list_windows`   枚举桌面上所有可见窗口，用于下拉选择
- :meth:`WindowTools.window_at_point` 取某个屏幕坐标下最顶层的窗口，用于「鼠标点选」
"""

from __future__ import annotations

import os
import platform
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"

# ---------------------------------------------------------------- 依赖探测

try:
    import pyautogui
except Exception:  # pragma: no cover - 运行环境缺少依赖
    pyautogui = None

try:
    import mss
except Exception:
    mss = None

try:
    import pyscreeze
except Exception:
    pyscreeze = None

try:
    import cv2  # noqa: F401

    HAS_OPENCV = True
except Exception:
    HAS_OPENCV = False

try:
    import keyboard
except Exception:
    keyboard = None


class DependencyStatus:
    """一次性汇总运行环境的能力，供 GUI / 日志展示给用户。"""

    @staticmethod
    def report() -> dict:
        return {
            "system": SYSTEM,
            "python": platform.python_version(),
            "pyautogui": bool(pyautogui),
            "mss": bool(mss),
            "pyscreeze": bool(pyscreeze),
            "opencv": HAS_OPENCV,
            "keyboard_hotkey": bool(keyboard),
        }

    @staticmethod
    def human_readable() -> str:
        r = DependencyStatus.report()
        missing = [k for k in ("pyautogui", "keyboard_hotkey") if not r[k]]
        notes = []
        if not HAS_OPENCV:
            notes.append("未安装 opencv-python：图像步骤只能做“像素完全一致”匹配，建议安装")
        if not mss:
            notes.append("未安装 mss：截图退回 pyautogui，多显示器场景可能不完整")
        if missing:
            notes.append("缺失关键依赖：" + ", ".join(missing))
        return "；".join(notes) if notes else "运行环境完整"


# ---------------------------------------------------------------- DPI 感知


def enable_dpi_awareness() -> bool:
    """Windows 下开启进程级 DPI 感知。

    不做这件事时，系统会把鼠标坐标虚拟化（例如 150% 缩放下返回逻辑坐标），
    而截图拿到的是物理像素，两者错位会导致“坐标明明对着，点下去却偏了”。
    打开感知后二者都以物理像素为准，1080p 上也毫无副作用。
    """
    if SYSTEM != "Windows":
        return False
    try:
        import ctypes

        # 2 = PROCESS_PER_MONITOR_DPI_AWARE（支持多显示器不同缩放）
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------- 屏幕截图


class Grabber:
    """截图抓取：优先 mss（整块虚拟桌面、支持负坐标、macOS Retina 也可靠）。"""

    def __init__(self) -> None:
        self._mss = None
        self._lock = threading.Lock()
        self.scale = 1.0  # 物理像素 / 逻辑坐标 的比值
        self._measured = False

    def _ensure_mss(self):
        if mss is None:
            return None
        if self._mss is None:
            with self._lock:
                if self._mss is None:
                    try:
                        self._mss = mss.mss()
                    except Exception:
                        self._mss = False
        return self._mss or None

    def grab(self):
        """返回 PIL.Image；失败时抛异常由调用方处理。"""
        sct = self._ensure_mss()
        if sct is not None:
            monitor = sct.monitors[0]  # 0 = 包含所有显示器的虚拟桌面
            raw = sct.grab(monitor)
            from PIL import Image

            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            return img, (monitor["left"], monitor["top"])
        if pyautogui is None:
            raise RuntimeError("缺少截图依赖：请安装 pyautogui 或 mss")
        img = pyautogui.screenshot()
        return img, (0, 0)

    def measure_scale(self) -> float:
        """对比“截图物理宽度”与“pyautogui 逻辑宽度”，得到高分屏缩放比。

        Windows 开启 DPI 感知后恒为 1.0；macOS Retina 通常为 2.0。
        """
        if self._measured:
            return self.scale
        self._measured = True
        try:
            logical_w = pyautogui.size()[0] if pyautogui else None
            img, _ = self.grab()
            if logical_w and img.width:
                ratio = img.width / float(logical_w)
                if 0.5 <= ratio <= 4:
                    self.scale = ratio
        except Exception:
            self.scale = 1.0
        return self.scale


# ---------------------------------------------------------------- 模板匹配

_warned_modes = set()


def locate_center(template_path: str, confidence: float = 0.9, grabber: Optional[Grabber] = None):
    """在整块虚拟屏幕上定位模板图片，返回 ``(x, y)``（逻辑坐标）或 ``None``。

    - 有 OpenCV：支持 confidence 相似度匹配（推荐安装 opencv-python）
    - 无 OpenCV：自动退回“像素完全一致”匹配，并在首次调用时提示
    """
    if pyautogui is None and pyscreeze is None:
        raise RuntimeError("缺少图像依赖：请安装 pyautogui")

    grabber = grabber or Grabber()
    use_confidence = HAS_OPENCV and confidence < 0.999
    if confidence < 0.999 and not HAS_OPENCV and "confidence" not in _warned_modes:
        _warned_modes.add("confidence")
        print("[提示] 未检测到 opencv-python，图像步骤退化为精确像素匹配（confidence 参数暂不生效）")

    try:
        if pyscreeze is not None:
            img, (ox, oy) = grabber.grab()
            box = pyscreeze.locate(
                template_path,
                img,
                confidence=confidence if use_confidence else 1.0,
                grayscale=use_confidence,
            )
            if box is None:
                return None
            scale = grabber.measure_scale()
            cx = ox + box.left + box.width / 2.0
            cy = oy + box.top + box.height / 2.0
            return (int(cx / scale), int(cy / scale))

        # 兜底：让 pyautogui 自己截图（只覆盖主显示器）
        try:
            return pyautogui.locateCenterOnScreen(
                template_path,
                confidence=confidence if use_confidence else None,
                grayscale=use_confidence,
            )
        except Exception:
            box = pyautogui.locateOnScreen(template_path)
            if box is None:
                return None
            return pyautogui.center(box)
    except Exception:
        return None


# ---------------------------------------------------------------- 窗口工具


@dataclass
class WindowInfo:
    """一个桌面上可见的顶层窗口。

    ``handle`` 在 win32gui 后端下是真正的 ``HWND``，pygetwindow 后端下为 0；
    ``process`` 是尽量获取的进程名（拿不到就留空），仅用于下拉列表显示。
    """

    title: str
    left: int
    top: int
    width: int
    height: int
    handle: int = 0
    process: str = ""

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    def display(self, limit: int = 40) -> str:
        """下拉列表里的展示文本：进程名 · 裁剪后的标题。"""
        title = self.title.strip() or "(无标题)"
        if len(title) > limit:
            title = title[: limit - 1] + "…"
        return f"{self.process} · {title}" if self.process else title


class WindowTools:
    """窗口枚举与命中检测，按可用性逐级降级：win32gui → pygetwindow → 关闭该功能。

    三种取窗口的方式各有用武之地：

    - :meth:`active_title`——适合在倒计时结束后采样（按钮回调里调用只会读到本程序）；
    - :meth:`list_windows`——给下拉框用，用户不必手打标题；
    - :meth:`window_at_point`——配合半透明浮层做「鼠标点选」，最直观。
    """

    backend: str = "none"

    def __init__(self) -> None:
        self._win32 = None
        self._pygetwindow = None
        self._win32process = None
        if SYSTEM == "Windows":
            try:
                import win32gui  # noqa: F401

                self._win32 = win32gui
                self.backend = "win32gui"
            except Exception:
                self._win32 = None
            try:
                import win32process  # noqa: F401

                self._win32process = win32process
            except Exception:
                self._win32process = None
        if self.backend == "none":
            try:
                import pygetwindow  # noqa: F401

                self._pygetwindow = pygetwindow
                self.backend = "pygetwindow"
            except Exception:
                self.backend = "none"

    # ------------------------------------------------------------ 枚举 / 命中

    def list_windows(self, include_minimized: bool = False) -> List[WindowInfo]:
        """枚举桌面上所有可见的顶层窗口（按 Z 序从前往后）。

        无可用后端时返回空列表——调用方据此提示用户手动填写，而不是抛异常。
        """
        items: List[WindowInfo] = []
        if self._win32 is not None:
            items = self._list_windows_win32(include_minimized)
        elif self._pygetwindow is not None:
            items = self._list_windows_pygw(include_minimized)
        return items

    def _list_windows_win32(self, include_minimized: bool) -> List[WindowInfo]:
        items: List[WindowInfo] = []

        def _cb(hwnd, _):
            try:
                w = self._win32
                if not w.IsWindowVisible(hwnd):
                    return True
                if not include_minimized and w.IsIconic(hwnd):
                    return True
                left, top, right, bottom = w.GetWindowRect(hwnd)
                width, height = right - left, bottom - top
                # 最小化到任务栏的窗口会被系统挪到坐标 -32000 附近
                if width <= 1 or height <= 1 or left < -30000 or top < -30000:
                    return True
                title = (w.GetWindowText(hwnd) or "").strip()
                items.append(WindowInfo(title=title, left=left, top=top, width=width,
                                        height=height, handle=hwnd,
                                        process=self._win32_process_name(hwnd)))
            except Exception:
                pass
            return True

        try:
            self._win32.EnumWindows(_cb, None)
        except Exception:
            return []
        return items

    def _list_windows_pygw(self, include_minimized: bool) -> List[WindowInfo]:
        items: List[WindowInfo] = []
        try:
            for win in self._pygetwindow.getAllWindows():
                try:
                    title = (win.title or "").strip()
                    width, height = int(win.width), int(win.height)
                    left, top = int(win.left), int(win.top)
                    if width <= 1 or height <= 1 or left < -30000 or top < -30000:
                        continue
                    if not include_minimized and title.lower() in ("", "screencapture"):
                        continue
                    items.append(WindowInfo(title=title, left=left, top=top,
                                            width=width, height=height))
                except Exception:
                    continue
        except Exception:
            return []
        return items

    def _win32_process_name(self, hwnd: int) -> str:
        """尽力取进程名，拿不到就返回空串（不影响下拉可用性）。

        刻意只用可选依赖 psutil，不退化到 ``tasklist``——后者每查一个窗口都要
        起一个子进程，几十个窗口会让下拉刷新卡住好几秒。
        """
        if self._win32process is None:
            return ""
        try:
            import psutil
        except Exception:
            return ""
        try:
            _, pid = self._win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                return psutil.Process(pid).name().replace(".exe", "")
        except Exception:
            return ""
        return ""

    def window_at_point(self, x: int, y: int, exclude_handle: int = 0,
                        exclude_title: str = "") -> Optional[WindowInfo]:
        """取屏幕坐标 ``(x, y)`` 处最顶层的窗口，自动跳过排除项。

        Windows 下 ``EnumWindows`` 的枚举顺序本身就是 Z 序（最上层在前），
        因此只要按顺序做矩形命中测试，第一个命中的就是「肉眼看到的那个窗口」，
        顺带自然跳过了覆盖在上面的半透明选择器浮层。
        """
        for info in self.list_windows(include_minimized=True):
            if info.handle and info.handle == exclude_handle:
                continue
            if exclude_title and info.title == exclude_title:
                continue
            if info.contains(x, y):
                return info
        return None

    def find_by_title(self, title: str) -> Optional[WindowInfo]:
        """按标题包含匹配（忽略大小写）查找第一个命中的窗口，用于取它的矩形。"""
        if not title:
            return None
        key = title.lower()
        for info in self.list_windows(include_minimized=True):
            if key in info.title.lower():
                return info
        return None

    def activate(self, title: str) -> Tuple[bool, str]:
        """把标题包含匹配的窗口切到前台。

        返回 ``(是否成功, 说明)``——失败时说明里给出原因，交给上层提示用户切,
        而不是抛异常中断任务。
        """
        if self.backend == "none":
            return False, "当前平台不支持窗口枚举，无法自动切换"
        info = self.find_by_title(title)
        if info is None:
            return False, f"桌面上找不到标题包含“{title}”的窗口"
        try:
            if self._win32 is not None and info.handle:
                hwnd = info.handle
                w = self._win32
                if w.IsIconic(hwnd):
                    w.ShowWindow(hwnd, 9)  # SW_RESTORE
                try:
                    w.SetForegroundWindow(hwnd)
                except Exception:
                    # 系统不允许后台进程抢焦点时退而求其次：先 BringToTop
                    w.BringWindowToTop(hwnd)
                    w.SetForegroundWindow(hwnd)
                return w.GetForegroundWindow() == hwnd, ""
            if self._pygetwindow is not None:
                for win in self._pygetwindow.getAllWindows():
                    if title.lower() in (win.title or "").lower():
                        win.activate()
                        return True, ""
        except Exception as exc:
            return False, f"切换窗口失败：{exc}"
        return False, "未能激活目标窗口（可能被系统限制了抢焦点）"

    # ------------------------------------------------------------ 前台

    def active_title(self) -> Optional[str]:
        try:
            if self._win32 is not None:
                return self._win32.GetWindowText(self._win32.GetForegroundWindow())
            if self._pygetwindow is not None:
                win = self._pygetwindow.getActiveWindow()
                return win.title if win else None
        except Exception:
            return None
        return None

    def is_title_active(self, title: str) -> bool:
        """标题包含匹配（忽略大小写），后台窗口识别不可用时会给出明确提示。"""
        if not title:
            return True
        if self.backend == "none":
            # 能力不可用时不阻拦任务，交给用户自行判断是否切换窗口
            return True
        current = self.active_title() or ""
        return title.lower() in current.lower()

    def active_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """返回 ``(left, top, width, height)``，用于窗口相对坐标。"""
        try:
            if self._win32 is not None:
                hwnd = self._win32.GetForegroundWindow()
                rect = self._win32.GetWindowRect(hwnd)
                return (rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
            if self._pygetwindow is not None:
                win = self._pygetwindow.getActiveWindow()
                if win:
                    return (win.left, win.top, win.width, win.height)
        except Exception:
            return None
        return None


# ---------------------------------------------------------------- 其它小工具


def resource_path(*parts: str) -> str:
    """相对项目根目录拼路径，兼容打包 / 不同工作目录调用。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def safe_sleep(seconds: float, stop_event: Optional[threading.Event] = None) -> None:
    """可被中止的 sleep：停止信号一到立刻返回，避免“停了还在点”。"""
    if seconds <= 0:
        return
    step = 0.05
    waited = 0.0
    while waited < seconds:
        if stop_event is not None and stop_event.is_set():
            return
        import time as _t

        _t.sleep(min(step, seconds - waited))
        waited += step
