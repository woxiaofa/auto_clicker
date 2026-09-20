"""命令行接口：给喜欢跑脚本 / 需要无人值守的用户。

典型用法：

    python -m autoclicker.cli profiles/example.json            # 循环执行到底
    python -m autoclicker.cli profiles/example.json --once 3   # 执行 3 轮后自动退出
    python -m autoclicker.cli profiles/example.json --dry-run  # 空跑自检，不真的操作鼠标
    python -m autoclicker.cli --list-steps profiles/example.json

热键（需要 keyboard 库，Linux 下一般要 root）：
    F9 开始 / F10 停止 / Ctrl+Alt+Q 退出
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from .engine import Engine
from .platform_adapter import DependencyStatus, enable_dpi_awareness
from .profile import Profile, example_profile


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autoclicker",
                                description="跨平台自动点击器 · 命令行模式")
    p.add_argument("profile", nargs="?", help="任务配置文件 JSON")
    p.add_argument("--once", type=int, default=0, metavar="N",
                   help="执行 N 轮后自动退出（覆盖配置里的循环设置）")
    p.add_argument("--loop-count", type=int, default=0, metavar="N", help="循环 N 轮")
    p.add_argument("--countdown", type=float, default=None, help="开始前倒计时秒数")
    p.add_argument("--dry-run", action="store_true", help="空跑：只打印日志，不操作鼠标键盘")
    p.add_argument("--target-window", default=None, help="目标窗口标题（包含匹配）")
    p.add_argument("--no-hotkey", action="store_true", help="不注册全局热键")
    p.add_argument("--list-steps", action="store_true", help="只列出步骤然后退出")
    p.add_argument("--create-example", metavar="PATH", help="生成一份示例配置并退出")
    p.add_argument("--doctor", action="store_true", help="打印运行环境自检结果后退出")
    p.add_argument("-v", "--verbose", action="store_true", help="输出详细环境信息")
    return p


def doctor() -> int:
    enable_dpi_awareness()
    report = DependencyStatus.report()
    print("=== 运行环境自检 ===")
    for k, v in report.items():
        print(f"  {k:>16}: {v}")
    print("  建议：", DependencyStatus.human_readable())
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    enable_dpi_awareness()

    if args.doctor:
        return doctor()

    if args.create_example:
        path = args.create_example
        example_profile().save(path)
        print(f"示例配置已生成：{path}")
        return 0

    if not args.profile:
        build_parser().print_help()
        return 1

    if not os.path.exists(args.profile):
        print(f"[错误] 找不到配置文件：{args.profile}")
        return 1

    profile = Profile.load(args.profile)

    if args.once:
        profile.settings.loop = False
        profile.settings.loop_count = args.once
    if args.loop_count:
        profile.settings.loop = False
        profile.settings.loop_count = args.loop_count
    if args.countdown is not None:
        profile.settings.countdown = args.countdown
    if args.dry_run:
        profile.settings.dry_run = True
    if args.target_window:
        profile.settings.target_window = args.target_window

    if args.list_steps:
        print(f"任务：{profile.name}（共 {len(profile.steps)} 步）")
        for i, s in enumerate(profile.steps, 1):
            flag = "✓" if s.enabled else "×"
            print(f"  {i:>2}. [{flag}] {s.describe()}")
        return 0

    if args.verbose:
        report = DependencyStatus.report()
        print("[环境]", ", ".join(f"{k}={v}" for k, v in report.items()))

    engine = Engine(profile)
    engine.on_log = lambda level, msg: print(msg)

    hotkey_stopped = False
    if not args.no_hotkey:
        try:
            import keyboard

            keyboard.add_hotkey("f9", engine.start)
            keyboard.add_hotkey("f10", engine.stop)
            print("热键已注册：F9 开始 / F10 停止 / Ctrl+C 退出")
        except Exception as exc:
            print(f"[警告] 热键不可用（{exc}），请用 Ctrl+C 控制")

    print(f"任务：{profile.name} | 模式：{'空跑' if profile.settings.dry_run else '真实执行'}"
          f" | 循环：{'是' if profile.settings.loop else profile.settings.loop_count}")

    engine.start()
    try:
        while engine.running or (engine._thread and engine._thread.is_alive()):
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在停止…")
        engine.stop()
        engine.wait_until_finished(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
