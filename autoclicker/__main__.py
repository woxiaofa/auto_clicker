"""``python -m autoclicker`` 入口：不带参数启动图形界面，带参数走命令行。"""

from __future__ import annotations

import sys

from .platform_adapter import enable_dpi_awareness


def main() -> int:
    enable_dpi_awareness()
    args = sys.argv[1:]
    # 只有显式给出子命令或参数时才走 CLI，否则默认开界面
    cli_triggers = ("--help", "-h", "--doctor", "--create-example", "--list-steps",
                    "--dry-run", "--once", "--loop-count", "--no-hotkey")
    want_cli = bool(args) and (args[0].endswith(".json") or args[0] in cli_triggers
                               or any(a in cli_triggers for a in args))
    if want_cli:
        from .cli import main as cli_main

        return cli_main(args)

    try:
        from .gui import launch

        profile = args[0] if args and args[0].endswith(".json") else None
        launch(profile)
        return 0
    except ImportError as exc:
        print(f"[提示] 当前环境无法启动图形界面（{exc}）")
        print("可以改用命令行模式：python -m autoclicker.cli 配置文件.json --once 1")
        return 1


if __name__ == "__main__":
    sys.exit(main())
