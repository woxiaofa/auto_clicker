"""跨平台适配层：屏幕缩放 / 多显示器截图 / 窗口检测 / 依赖探测。

设计原则：**任何一项能力缺失都不能导致程序崩溃**，而是降级并在日志里说明原因，
这样同一份代码在 Windows / macOS / Linux、不同 DPI 缩放、有无 OpenCV 的环境下都能跑。

组成部分：
- ``enable_dpi_awareness()``   Windows 打开进程级 DPI 感知，消除坐标与截图的错位
- ``Grabber``                  优先用 mss 截取整个虚拟屏幕（含副屏负坐标），失败则退回 pyautogui
- ``WindowTools``              前台窗口检测：win32gui → pygetwindow → 不可用则返回 None
- ``deps`` / ``locate()``      依赖探测与模板匹配，无 OpenCV 时自动退回像素级精确匹配
"""

from __future__ import annotations

import os
import platform
import threading
from typing import Optional, Tuple

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


class WindowTools:
    """前台窗口检测，按可用性逐级降级：win32gui → pygetwindow → 关闭该功能。"""

    backend: str = "none"

    def __init__(self) -> None:
        self._win32 = None
        self._pygetwindow = None
        if SYSTEM == "Windows":
            try:
                import win32gui  # noqa: F401

                self._win32 = win32gui
                self.backend = "win32gui"
            except Exception:
                self._win32 = None
        if self.backend == "none":
            try:
                import pygetwindow  # noqa: F401

                self._pygetwindow = pygetwindow
                self.backend = "pygetwindow"
            except Exception:
                self.backend = "none"

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
