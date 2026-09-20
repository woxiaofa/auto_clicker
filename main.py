"""双击即可运行的入口脚本：默认打开图形界面。

用法：
    python main.py                # 打开可视化界面
    python main.py xx.json        # 载入指定配置打开界面
    python main.py --doctor       # 运行环境自检
    python main.py xx.json --once 1 --dry-run   # 命令行模式（更多见 autoclicker/cli.py）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autoclicker.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
