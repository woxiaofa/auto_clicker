"""跨平台自动点击器 Auto Clicker。

一个主打“配置化 + 可视化”的桌面自动化小工具：
把原来写死在代码里的坐标，变成可在图形界面里编辑、随 JSON 配置保存与分享的步骤序列。

主要模块：
- ``platform_adapter`` : DPI 感知 / 多屏截图 / 窗口检测 / 依赖探测与优雅降级
- ``profile``          : 任务与步骤的数据模型（JSON 持久化）
- ``engine``           : 执行引擎（中止 / 暂停 / 空跑 / 失败保护）
- ``gui``              : tkinter 可视化编辑器
- ``cli``              : 命令行接口
"""

__version__ = "2.0.0"
__author__ = "woxiaofa"

from .profile import Profile, Settings, Step, example_profile, STEP_KINDS  # noqa: F401

__all__ = ["Profile", "Settings", "Step", "example_profile", "STEP_KINDS", "__version__"]
