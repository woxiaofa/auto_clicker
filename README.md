# 自动点击器 · Auto Clicker

> 一个**跨平台、可配置、带图形界面**的桌面鼠标键盘自动化小工具。
> 把原来写死在代码里的坐标，变成能在界面里增删改、存成 JSON、随时分享复用的「任务步骤」。

跨平台 Cross-platform · 可视化编辑器 Visual editor · 多显示器 Multi-monitor · DPI 自适应 DPI-aware · 图片识别 Image detection · MIT

---

## ✨ 为什么重写一版

原版本是一部「为某个界面量身定做」的脚本：坐标硬编码、`win32gui` 写死导致**只能在 Windows 跑**、改一次参数就要动代码、三个独立脚本（取坐标 / 截图 / 执行）来回切换。这一版针对这几点做了重构：

| 痛点 | 原版本 | 现在 |
| --- | --- | --- |
| **系统兼容** | 仅 Windows（`import win32gui` 在 mac/Linux 直接崩） | Windows / macOS / Linux 三平台，窗口检测按 `win32gui → pygetwindow → 不可用则跳过` 逐级降级 |
| **坐标维护** | 散落在 `auto_clicker.py` 里 | 图形界面增删改排序，存成 JSON 配置 |
| **屏幕缩放** | 25%/150% 缩放下坐标偏移 | 进程级 DPI 感知 + 高分屏比例自动换算 |
| **多显示器** | 副屏负坐标容易失效 | 用 `mss` 抓整块虚拟桌面，负坐标也正确 |
| **依赖缺失** | 少一个包就启动失败 | 全部依赖可选：`opencv` 缺席→退化为精确匹配，`mss` 缺席→退回 pyautogui，`keyboard` 缺席→改用界面按钮 |
| **取坐标 / 截图** | 三个命令行小脚本 | 界面内置坐标拾取器（跟随鼠标显示坐标）、区域框选截图、目标窗口点选器 |
| **取窗口标题** | 手抄标题到输入框 | 「点选」直接拿鼠标底下的窗口，「列表」枚举桌面所有窗口下拉选择 |
| **中止响应** | 停止信号只在若干处检查 | 每个动作与等待都响应停止，不会出现「停了还点两下」 |
| **误操作风险** | 直接开跑 | 开始倒计时 + 目标窗口校验 + 左上角急停 + **空跑自检** |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
python -m pip install -r requirements.txt
```

最小可用组合：`pyautogui` + `pillow`。想要完整能力建议再装 `mss`（多屏截图）、`opencv-python`（模糊匹配）、`keyboard`（全局热键）、`pyperclip`（输入中文）。

### 2. 打开图形界面

```bash
python main.py
```

第一次使用点右上角「**载入示例**」，照着改坐标就能跑。

### 3. 三分钟上手流程

1. **拾取坐标**：步骤框里点「新增」→ 在坐标区点「**拾取坐标**」→ 屏幕出现半透明浮层，鼠标移到目标按钮上，**按空格锁定**
2. **调整节奏**：设置每个步骤的「后置等待」；勾选全局随机抖动可让操作更像人工节奏
3. **空跑自检**：勾选「空跑（只记录不操作）」先跑一轮，确认日志顺序正确
4. **正式运行**：取消勾选空跑，设置倒计时（默认 3 秒用于切窗口），点「开始」

> ⚠️ 建议先 `--dry-run` / 勾选空跑，确认步骤无误再真实执行。

---

## 🖥 界面功能

| 区域 | 说明 |
| --- | --- |
| 工具栏 | 新建 / 打开 / 保存 / 另存 / 载入示例 |
| 步骤列表 | 增删改、复制、上下移动排序；双击行进入编辑 |
| 任务设置 | 循环开关与轮数、开始倒计时、目标窗口（下拉 / 点选 / 手填）、「自动切到目标窗口」与「不在前台时等待」、左上角急停、空跑、随机抖动、动作最小间隔 |
| 运行控制 | 开始 / 暂停 / 停止，实时状态条 + 环境自检提示 |
| 日志面板 | 分级彩色输出，同时写入 `logs/run.log` |

**9 种步骤类型**：单击、双击、右键、仅移动鼠标、按键/组合键、输入文本、滚轮滚动、等待（秒）、等待图片出现后点击。

**坐标模式**：

- **绝对坐标**：适合窗口位置固定的场景
- **相对目标窗口**：记录相对窗口左上角的偏移，窗口拖动后依然准确（依赖窗口检测能力，不可用时会在日志里提示）

**图片步骤**：支持多张模板，任一命中即点击其中心；相似度可调（需 OpenCV）；勾选「找不到时不报错」则为可选步骤，超时自动跳过。

### 选择目标窗口的三种方式

免手打标题，任选其一：

| 方式 | 操作 | 适合场景 |
| --- | --- | --- |
| **🎯 点选** | 点「点选」→ 鼠标移到目标窗口上 → 四周出现红框和标题 → 单击即填入 | 最直观，尤其适合标题很长或带动态内容（文件名、网址）的窗口 |
| **📋 列表** | 点「列表」→ 下拉框展开当前桌面所有可见窗口，按面积排序，点一下即可 | 目标窗口被挡住、不方便把鼠标移过去时 |
| **⌨️ 手填** | 直接在输入框写关键字 | 标题会在运行中变化（如「文档 - 记事本」只填「记事本」） |

匹配规则是**标题包含匹配、忽略大小写**，所以填关键字比填完整标题更稳。

配套两个开关：

- **开始前自动切到目标窗口**（默认开）：倒计时结束的那一刻自动把目标窗口请到前台，不用手忙脚乱地点。
- **窗口不在前台时等待**：前面那个开关失败时（比如系统不允许后台程序抢焦点），是否停下来等你手动切过去；**不勾的话会带警告继续操作**——此时鼠标和键盘作用在当前的窗口上，请留意。

> 这些能力依赖 `win32gui`（Windows 自带，装了 pywin32 就有）或 `pygetwindow`。两者都不可用时，下拉和点选会给出提示，此时只能手填标题，窗口校验也会自动跳过。

---

## 🧰 命令行模式

```bash
# 循环执行
python -m autoclicker.cli profiles/example.json

# 执行 5 轮后自动退出
python -m autoclicker.cli profiles/example.json --once 5

# 空跑自检（强烈建议先跑一遍）
python -m autoclicker.cli profiles/example.json --dry-run --once 1

# 指定目标窗口，窗口不在前台则等待
python -m autoclicker.cli profiles/example.json --target-window "记事本" --require-window

# 指定窗口但禁止自动抢焦点（无人值守时避免打断别人操作）
python -m autoclicker.cli profiles/example.json --target-window "记事本" --no-auto-focus

# 只看步骤清单 / 生成示例配置 / 环境自检
python -m autoclicker.cli --list-steps profiles/example.json
python -m autoclicker.cli --create-example profiles/my.json
python -m autoclicker.cli --doctor
```

> `--target-window` 默认会在开始时尝试把该窗口切到前台（等价于界面上的「自动切到目标窗口」），
> 不想这样请用 `--no-auto-focus`。

热键（需 `keyboard` 库）：**F9 开始 / F10 停止**，命令行下 `Ctrl+C` 也可随时中止。

---

## 📄 配置文件格式

一个 JSON 文件就是一套完整流程，可以提交进仓库或发给同事复用：

```json
{
  "name": "示例：批量删除流程",
  "version": 1,
  "settings": {
    "loop": true,
    "countdown": 3.0,
    "target_window": "",
    "failsafe": true,
    "dry_run": false,
    "jitter": 0.0,
    "min_interval": 0.05
  },
  "steps": [
    { "kind": "click", "name": "全选", "x": 240, "y": 135, "coord_mode": "absolute", "delay_after": 0.1 },
    { "kind": "key", "name": "End 到底部", "keys": "end", "delay_after": 0.4 },
    { "kind": "wait_image", "name": "关闭按钮", "images": ["templates/close_button_normal.png"],
      "confidence": 0.8, "timeout": 5.0, "optional": true }
  ]
}
```

`steps[].kind` 取值：`click` `double_click` `right_click` `move` `key` `text` `scroll` `wait` `wait_image`。
未知字段会被保留，旧配置不会因为升级而丢数据。

---

## 🧩 兼容性矩阵

| 平台 | 鼠标键盘操作 | 窗口检测 | 全局热键 | 备注 |
| --- | --- | --- | --- | --- |
| **Windows** | ✅ | ✅ pywin32 | ✅ | 自动开启进程级 DPI 感知；建议用管理员权限运行被操作的目标程序 |
| **macOS** | ✅ | ⚠️ 需装 `pygetwindow` | ⚠️ 需 root + 辅助功能权限 | 需在「系统设置 → 隐私与安全性 → 辅助功能」中给终端授权 |
| **Linux** | ✅ X11（Wayland 有限） | ⚠️ 需装 `pygetwindow` | ⚠️ 需 root | Wayland 下 pyautogui 支持不完善，建议切回 Xorg |

三平台统一的降级策略：**任何可选能力缺失都只在日志里告警，不阻止主流程**。

---

## ❓ 常见问题

**坐标明明是对的，点下去却偏了**
显示缩放不是 100% 导致的。Windows 上程序会自动开启 DPI 感知；若仍偏移，优先以与目标程序相同的权限运行，必要时都用管理员权限（权限不同的进程，坐标与输入可能被系统隔离）。

**截图是黑屏 / 图片步骤永远找不到**
以与目标程序相同的权限运行；笔记本双显卡可在「系统 → 显示 → 图形设置」把 Python 设为「省电」；必要时降级 `pip install pyautogui==0.9.53`。

**提示 “confidence 参数暂不生效”**
没装 OpenCV，图像步骤退化为「像素完全一致」匹配。安装 `opencv-python` 后自动恢复相似度匹配。

**副屏/负坐标点击不对**
请确保安装了 `mss`（`pip install mss`），它会抓取包含所有显示器的虚拟桌面；未安装时只能覆盖主显示器。

**热键注册失败**
Linux 需 root，macOS 需辅助功能权限；Windows 一般以管理员运行即可。热键不可用时用界面按钮或 `Ctrl+C` 控制，不影响自动化本身。

**中文输入不生效**
需要 `pyperclip`（走剪贴板粘贴）；不装的话日志会提示并跳过该步骤。

---

## 🔒 安全与使用约定

- **左上角急停**：默认开启，鼠标甩到屏幕左上角触发 `FailSafeException` 中止
- **开始倒计时**：给你切到目标窗口的时间。若填了目标窗口，倒计时结束的时刻还会自动把它切到前台
- **空跑模式**：只打日志不操作，用来验证步骤顺序
- **目标窗口校验**：避免前台不是目标窗口时误敲键盘；自动切换失败时会明确告诉你，由你决定退出还是继续

> 本工具用于个人效率提升与学习研究。请勿用于违反目标软件服务条款、损害他人权益或涉及资金/审核类高风险操作的场景，由此产生的后果由使用者自行承担。

---

## 📁 目录结构

```
auto_clicker/
├── main.py                     # 双击运行的入口
├── autoclicker/
│   ├── __init__.py
│   ├── __main__.py             # python -m autoclicker
│   ├── cli.py                  # 命令行接口
│   ├── gui.py                  # tkinter 图形界面 + 坐标拾取器 + 区域截图 + 窗口点选器
│   ├── engine.py               # 执行引擎（中止/暂停/空跑/失败保护/自动聚焦）
│   ├── profile.py              # 任务与步骤数据模型（JSON 持久化）
│   └── platform_adapter.py     # 跨平台适配：DPI/多屏截图/窗口/依赖降级
├── profiles/example.json       # 示例配置
├── templates/                  # 图片模板
├── legacy/                     # 旧版脚本（保留备查）
└── requirements.txt
```

---

## 🤝 贡献

欢迎 Issue 与 PR。新增步骤类型只需改 `autoclicker/profile.py` 里的 `STEP_KINDS` 并在 `engine.py` 中加一个分支逻辑。

## 📜 许可证

[MIT](LICENSE) © 2026

---

**关键词 Keywords**: 自动点击器, 鼠标连点, 键鼠自动化, 桌面自动化, 坐标拾取, 图片识别点击, 跨平台 Python 工具, auto clicker, mouse automation, GUI automation, pyautogui, tkinter, multi-monitor, DPI aware
