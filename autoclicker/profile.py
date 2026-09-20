"""配置数据模型：把“硬编码坐标”改成可保存、可分享的 JSON 配置文件（profile）。

一个 profile 就是一次自动化任务的完整描述：

    {
      "name": "批量删除示例",
      "version": 1,
      "settings": { ... },
      "steps": [ ... ]
    }

这样带来的直接好处：
- 换电脑 / 换分辨率不再需要改代码，改 JSON 或点几下鼠标即可
- 可以把配置提交到仓库或发给同事复用
- 支持“窗口相对坐标”，窗口挪动亦不影响
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

# 支持的步骤类型；GUI 的下拉框直接取这里，新增类型只需改这一处
STEP_KINDS = {
    "click": "单击",
    "double_click": "双击",
    "right_click": "右键单击",
    "move": "仅移动鼠标",
    "key": "按键 / 组合键",
    "text": "输入文本",
    "scroll": "滚轮滚动",
    "wait": "等待（秒）",
    "wait_image": "等待图片出现后点击",
}

CoordModeAbsolute = "absolute"
CoordModeWindow = "window"


@dataclass
class Step:
    """一个自动化动作。"""

    kind: str = "click"
    name: str = ""
    enabled: bool = True

    # --- 坐标相关 ---
    x: int = 0
    y: int = 0
    coord_mode: str = CoordModeAbsolute  # absolute | window（相对目标窗口左上角）

    # --- 按键 / 文本 / 滚动 ---
    keys: str = ""            # 如 "end"、"ctrl+s"
    text: str = ""
    scroll: int = 0

    # --- 图像识别 ---
    images: List[str] = field(default_factory=list)  # 模板图片路径（任一命中即视为找到）
    confidence: float = 0.85
    timeout: float = 5.0        # 等待图片的最长时间
    optional: bool = False      # 找不到图片时跳过而不报错

    # --- 节奏控制 ---
    delay_before: float = 0.0
    delay_after: float = 0.2
    jitter: float = 0.0         # 在 delay 上叠加 0~jitter 秒随机抖动，让节奏更像人

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # 兼容历史配置中的未知字段
    extra: Dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        """给 GUI 列表和日志用的简短描述。"""
        label = self.name.strip() or STEP_KINDS.get(self.kind, self.kind)
        if self.kind in ("click", "double_click", "right_click", "move"):
            return f"{label} @ ({self.x}, {self.y})"
        if self.kind == "key":
            return f"{label} [{self.keys}]"
        if self.kind == "text":
            preview = self.text if len(self.text) <= 12 else self.text[:12] + "…"
            return f"{label} “{preview}”"
        if self.kind == "scroll":
            return f"{label} {self.scroll}"
        if self.kind == "wait":
            return f"{label} {self.delay_after}s"
        if self.kind == "wait_image":
            return f"{label} {os.path.basename(self.images[0]) if self.images else '(未设置)'}"
        return label


@dataclass
class Settings:
    """任务级参数。"""

    loop: bool = True             # True=无限循环；False=执行 N 轮后停止
    loop_count: int = 1
    countdown: float = 3.0        # 开始前倒计时，留时间切到目标窗口
    target_window: str = ""       # 目标窗口标题包含匹配；留空表示不校验
    min_interval: float = 0.05    # 两个动作之间的最小间隔，防止操作过快导致界面跟不上
    mouse_duration: float = 0.05  # 鼠标移动时长
    failsafe: bool = True         # 鼠标移到屏幕左上角急停
    require_window: bool = False  # 目标窗口不在前台时是否暂停等待
    auto_focus: bool = True       # 开始前自动把目标窗口切到前台（配合上面的 target_window）
    dry_run: bool = False         # 空跑：只打日志不真的操作
    log_to_file: bool = True
    log_file: str = "logs/run.log"
    jitter: float = 0.0           # 全局抖动


@dataclass
class Profile:
    name: str = "未命名任务"
    version: int = SCHEMA_VERSION
    settings: Settings = field(default_factory=Settings)
    steps: List[Step] = field(default_factory=list)

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version,
                "settings": asdict(self.settings),
                "steps": [asdict(s) for s in self.steps]}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    # ---------------------------------------------------------------- 反序列化
    @staticmethod
    def load(path: str) -> "Profile":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Profile.from_dict(data)

    @staticmethod
    def from_dict(data: dict) -> "Profile":
        raw_settings = dict(data.get("settings") or {})
        known_s = {k: raw_settings.pop(k, v) for k, v in asdict(Settings()).items()}
        settings = Settings(**known_s)
        for k, v in raw_settings.items():  # 未知字段保留，避免旧配置丢数据
            setattr(settings, k, v)

        steps: List[Step] = []
        for raw in data.get("steps") or []:
            raw = dict(raw)
            known = {k: raw.pop(k, v) for k, v in asdict(Step()).items()}
            step = Step(**known)
            step.extra = raw
            steps.append(step)
        return Profile(name=data.get("name", "未命名任务"),
                       version=int(data.get("version", SCHEMA_VERSION)),
                       settings=settings, steps=steps)


def example_profile() -> Profile:
    """内置示例：把原脚本“全选 → 更多 → 删除 → End → 确定 → 关闭”的流程搬进配置。"""
    return Profile(
        name="示例：批量删除流程",
        settings=Settings(loop=True, countdown=3.0, target_window="", require_window=False),
        steps=[
            Step(kind="click", name="全选", x=240, y=135, delay_after=0.1),
            Step(kind="click", name="更多", x=434, y=135, delay_after=0.15),
            Step(kind="click", name="删除选项", x=460, y=276, delay_after=0.2),
            Step(kind="key", name="End 到底部", keys="end", delay_after=0.4),
            Step(kind="click", name="确定", x=786, y=640, delay_after=0.3),
            Step(kind="wait_image", name="关闭按钮（图片识别）",
                 images=["templates/close_button_normal.png"],
                 confidence=0.7, timeout=5.0, optional=True, delay_after=0.3),
        ],
    )
