"""执行引擎：读取 profile 并按顺序执行，支持中止 / 暂停 / 空跑 / 失败保护。

相比原始脚本的主要变化：

1. **坐标来源配置化**——不再写死在代码里，支持绝对坐标与“窗口相对坐标”
2. **可随时中止**——step 之间都检查停止信号，点了停止不会“多点几下”
3. **三种后端**——真实执行 / 空跑(``dry_run``) / 无 GUI 环境的纯后台
4. **窗口守卫**——目标窗口不在前台时按策略等待，不会误敲到别的窗口
5. **统一日志回调**——GUI 面板、命令行、日志文件共用一条日志流
"""

from __future__ import annotations

import datetime as _dt
import os
import random
import threading
import time
from typing import Callable, List, Optional

from .platform_adapter import (
    Grabber,
    WindowTools,
    locate_center,
    resource_path,
    safe_sleep,
    SYSTEM,
)
from .profile import CoordModeWindow, Profile, Settings, Step

LogCb = Callable[[str, str], None]   # (level, message)
StatusCb = Callable[[str], None]


class Engine:
    """任务执行器。UI 层通过回调拿到日志与状态，不参与任何界面逻辑。"""

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.running = False
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.grabber = Grabber()
        self.windows = WindowTools()
        self.on_log: Optional[LogCb] = None
        self.on_status: Optional[StatusCb] = None
        self.stats = {"rounds": 0, "actions": 0, "errors": 0}
        self._resolve_paths()

    # ------------------------------------------------------------ 基础设施
    def _resolve_paths(self) -> None:
        """模板图片支持相对仓库根目录的路径，避免换工作目录后找不到图。"""
        for s in self.profile.steps:
            resolved = []
            for p in s.images:
                if not p:
                    continue
                resolved.append(p if os.path.isabs(p) or os.path.exists(p) else resource_path(p))
            s.images = resolved

    def log(self, message: str, level: str = "info") -> None:
        line = f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {message}"
        if self.on_log:
            try:
                self.on_log(level, line)
            except Exception:
                pass
        else:
            print(line)
        st = self.profile.settings
        if st.log_to_file and st.log_file and not st.dry_run:
            try:
                path = st.log_file if os.path.isabs(st.log_file) else resource_path(st.log_file)
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def _status(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                pass

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self.running:
            self.log("任务已在运行中", "warn")
            return
        self.stop_event.clear()
        self.pause_event.clear()
        self.running = True
        self.stats = {"rounds": 0, "actions": 0, "errors": 0}
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self.running = False
        self._status("已停止")
        self.log("收到停止指令，等待当前动作结束…")

    def toggle_pause(self) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
            self._status("运行中")
            self.log("已继续")
        else:
            self.pause_event.set()
            self._status("已暂停")
            self.log("已暂停")

    def wait_until_finished(self, timeout: Optional[float] = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------ 主循环
    def _run(self) -> None:
        st: Settings = self.profile.settings
        try:
            self._setup_input()
            for i in range(int(st.countdown), 0, -1):
                if self.stop_event.is_set():
                    return
                self._status(f"{i} 秒后开始，请切到目标窗口")
                safe_sleep(1, self.stop_event)
            if self.stop_event.is_set():
                return

            self._status("运行中")
            self.log(f"任务开始：{self.profile.name}（{SYSTEM}，后端={'空跑' if st.dry_run else '真实执行'}）")

            rounds = 0
            while not self.stop_event.is_set():
                rounds += 1
                self.stats["rounds"] = rounds
                self.log(f"— 第 {rounds} 轮 —")
                self._run_once()
                if self.stop_event.is_set():
                    break
                if not st.loop and rounds >= max(1, st.loop_count):
                    self.log(f"已完成 {rounds} 轮，任务结束")
                    break
        except Exception as exc:  # 兜底，保证线程不会悄悄死掉
            self.stats["errors"] += 1
            self.log(f"任务异常终止：{exc}", "error")
        finally:
            self.running = False
            self._status("已停止")
            self.log(f"任务结束：共 {self.stats['rounds']} 轮 / {self.stats['actions']} 个动作 / "
                     f"{self.stats['errors']} 次异常")

    def _setup_input(self) -> None:
        import pyautogui as pag

        st = self.profile.settings
        pag.FAILSAFE = bool(st.failsafe)
        pag.PAUSE = max(0.0, float(st.min_interval))
        pag.MINIMUM_DURATION = 0.0
        pag.MINIMUM_SLEEP = 0.0
        pag.DARWIN_CATCH_UP_TIME = 0.0

    def _run_once(self) -> None:
        for index, step in enumerate(self.profile.steps):
            if self.stop_event.is_set():
                return
            self._wait_if_paused()
            if not step.enabled:
                continue
            self._status(f"执行：{step.describe()}")
            try:
                self._execute(index, step)
                self.stats["actions"] += 1
            except StopIteration:
                return
            except Exception as exc:
                self.stats["errors"] += 1
                self.log(f"步骤 {index + 1}（{step.describe()}）出错：{exc}", "error")
                safe_sleep(0.3, self.stop_event)

    def _wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.1)

    # ------------------------------------------------------------ 单个动作
    def _execute(self, index: int, step: Step) -> None:
        st = self.profile.settings
        self._sleep_with_jitter(step.delay_before, st.jitter + step.jitter)
        self._guard_window()

        if step.kind == "wait":
            pass
        elif step.kind == "wait_image":
            self._action_wait_image(step)
        elif step.kind == "click":
            x, y = self._coords(step)
            self._mouse(x, y, "click", st)
        elif step.kind == "double_click":
            x, y = self._coords(step)
            self._mouse(x, y, "double", st)
        elif step.kind == "right_click":
            x, y = self._coords(step)
            self._mouse(x, y, "right", st)
        elif step.kind == "move":
            x, y = self._coords(step)
            self._mouse(x, y, "move", st)
        elif step.kind == "key":
            self._key(step.keys, st)
        elif step.kind == "text":
            self._type_text(step.text, st)
        elif step.kind == "scroll":
            self._scroll(step.scroll, st)
        else:
            self.log(f"未知步骤类型 {step.kind}，已跳过", "warn")

        self._sleep_with_jitter(step.delay_after, st.jitter + step.jitter)

    # ------------------------------------------------------------ 具体动作实现
    def _coords(self, step: Step) -> tuple:
        x, y = int(step.x), int(step.y)
        if step.coord_mode == CoordModeWindow:
            rect = self.windows.active_rect()
            if rect:
                x, y = rect[0] + x, rect[1] + y
            elif self.profile.settings.dry_run:
                pass
            else:
                self.log("无法获取窗口位置，本次按绝对坐标处理", "warn")
        self._assert_on_screen(x, y)
        return x, y

    def _assert_on_screen(self, x: int, y: int) -> None:
        """坐标在虚拟屏幕之外时给出明确告警（副屏用户常见坑位）。"""
        try:
            import pyautogui as pag

            w, h = pag.size()
        except Exception:
            return
        if not (-4096 <= x <= 8192 and -4096 <= y <= 8192):
            self.log(f"坐标 ({x}, {y}) 超出合理范围，请检查显示器布局", "warn")

    def _mouse(self, x: int, y: int, mode: str, st: Settings) -> None:
        if st.dry_run:
            self.log(f"[空跑] 鼠标 {mode} -> ({x}, {y})")
            return
        import pyautogui as pag

        pag.moveTo(x, y, duration=max(0.0, st.mouse_duration))
        if mode == "click":
            pag.click()
        elif mode == "double":
            pag.doubleClick()
        elif mode == "right":
            pag.rightClick()

    def _key(self, keys: str, st: Settings) -> None:
        keys = (keys or "").strip()
        if not keys:
            return
        if st.dry_run:
            self.log(f"[空跑] 按键 -> {keys}")
            return
        import pyautogui as pag

        if "+" in keys:
            pag.hotkey(*[k.strip() for k in keys.split("+") if k.strip()])
        else:
            pag.press(keys)

    def _type_text(self, text: str, st: Settings) -> None:
        if not text:
            return
        if st.dry_run:
            self.log(f"[空跑] 输入文本 -> {text}")
            return
        import pyautogui as pag

        if any(ord(ch) > 127 for ch in text):
            # pyautogui.typewrite 不支持中文，走剪贴板粘贴，粘贴后恢复剪贴板内容
            try:
                import pyperclip

                old = pyperclip.paste()
                pyperclip.copy(text)
                pag.hotkey("ctrl", "v")
                threading.Timer(0.4, lambda: pyperclip.copy(old)).start()
                return
            except Exception:
                self.log("输入中文需要 pyperclip（pip install pyperclip），已跳过", "warn")
                return
        pag.typewrite(text, interval=0.01)

    def _scroll(self, amount: int, st: Settings) -> None:
        if st.dry_run:
            self.log(f"[空跑] 滚轮 -> {amount}")
            return
        import pyautogui as pag

        pag.scroll(int(amount))

    def _action_wait_image(self, step: Step) -> None:
        """等待任一模板图片出现，出现后点击其中心。

        这是原脚本里最脆弱的一环：固定坐标点击窗关闭按钮。换成基于图片的等待后，
        目标位置随界面变化也能兜住。
        """
        if not step.images:
            if not step.optional:
                self.log("图片步骤未配置模板图片", "error")
            return
        if self.profile.settings.dry_run:
            self.log(f"[空跑] 等待图片 {os.path.basename(step.images[0])}")
            return

        deadline = time.time() + max(0.1, step.timeout)
        last_print = 0.0
        while time.time() < deadline:
            if self.stop_event.is_set():
                raise StopIteration
            for tpl in step.images:
                if not os.path.exists(tpl):
                    continue
                pos = locate_center(tpl, step.confidence, self.grabber)
                if pos:
                    import pyautogui as pag

                    pag.moveTo(pos[0], pos[1], duration=max(0.0, self.profile.settings.mouse_duration))
                    pag.click()
                    self.log(f"命中模板 {os.path.basename(tpl)}，点击 ({pos[0]}, {pos[1]})")
                    return
            now = time.time()
            if now - last_print >= 1.0:
                last_print = now
                self.log(f"等待中，剩余 {max(0.0, deadline - now):.1f}s")
            safe_sleep(0.1, self.stop_event)

        msg = f"等待图片超时（{step.timeout}s）：{os.path.basename(step.images[0])}"
        if step.optional:
            self.log(msg + "，已跳过", "warn")
        else:
            self.log(msg, "error")

    # ------------------------------------------------------------ 辅助
    def _guard_window(self) -> None:
        """目标窗口校验：不在前台则按 require_window 决定等待还是继续。"""
        st = self.profile.settings
        title = (st.target_window or "").strip()
        if not title:
            return
        while not self.windows.is_title_active(title):
            if st.dry_run:
                return
            self.log(f"当前前台窗口不是“{title}”", "warn")
            if not st.require_window:
                break
            self._status(f"等待窗口：{title}")
            waited = 0.0
            while not self.windows.is_title_active(title) and waited < 10:
                safe_sleep(0.5, self.stop_event)
                waited += 0.5
                if self.stop_event.is_set():
                    raise StopIteration

    def _sleep_with_jitter(self, base: float, jitter: float) -> None:
        total = max(0.0, base)
        if jitter > 0:
            total += random.uniform(0, jitter)
        safe_sleep(total, self.stop_event)
