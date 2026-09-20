import pyautogui
import keyboard
import time

print("按钮坐标获取工具")
print("按空格键获取当前鼠标位置")
print("按 Esc 键退出")

positions = []
names = ["全选按钮", "更多按钮", "删除选项", "确定按钮", "关闭按钮"]
current = 0

while current < len(names):
    print(f"\n请将鼠标移动到 {names[current]} 位置，然后按空格键")
    keyboard.wait('space')
    pos = pyautogui.position()
    positions.append(pos)
    print(f"{names[current]} 坐标: {pos}")
    current += 1
    time.sleep(0.5)

print("\n所有坐标：")
for name, pos in zip(names, positions):
    print(f"{name}: {pos}") 