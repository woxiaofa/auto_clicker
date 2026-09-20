import pyautogui
import keyboard
import time

print("工具使用说明：")
print("1. 将鼠标移动到删除按钮的左上角")
print("2. 按空格键记录左上角坐标")
print("3. 将鼠标移动到删除按钮的右下角")
print("4. 再次按空格键完成截图")

# 等待第一个坐标
print("\n请移动鼠标到左上角位置...")
keyboard.wait('space')
x1, y1 = pyautogui.position()
print(f"左上角坐标: ({x1}, {y1})")

time.sleep(0.5)

# 等待第二个坐标
print("\n请移动鼠标到右下角位置...")
keyboard.wait('space')
x2, y2 = pyautogui.position()
print(f"右下角坐标: ({x2}, {y2})")

# 截图
try:
    screenshot = pyautogui.screenshot('delete_button_normal.png', region=(x1, y1, x2-x1, y2-y1))
    print("\n截图已保存为 delete_button_normal.png")
except Exception as e:
    print(f"截图失败: {e}") 