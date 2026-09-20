import pyautogui
import keyboard
import time
import tkinter as tk
from PIL import ImageGrab

def on_mouse_down(event):
    global start_x, start_y
    start_x = event.x_root
    start_y = event.y_root

def on_mouse_up(event):
    global start_x, start_y
    end_x = event.x_root
    end_y = event.y_root
    
    # 确保坐标是从左上到右下
    left = min(start_x, end_x)
    top = min(start_y, end_y)
    right = max(start_x, end_x)
    bottom = max(start_y, end_y)
    
    # 截图
    try:
        screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
        screenshot.save('close_button.png')
        print("截图已保存为 close_button.png")
    except Exception as e:
        print(f"截图失败: {e}")
    
    root.quit()

print("工具使用说明：")
print("1. 按空格键开始截图")
print("2. 用鼠标拖动选择关闭按钮区域")
print("3. 松开鼠标完成截图")

# 等待开始
keyboard.wait('space')
time.sleep(0.5)

# 创建透明窗口
root = tk.Tk()
root.attributes('-alpha', 0.3)  # 设置透明度
root.attributes('-fullscreen', True)
root.attributes('-topmost', True)

# 绑定鼠标事件
root.bind('<Button-1>', on_mouse_down)
root.bind('<ButtonRelease-1>', on_mouse_up)

# 运行
root.mainloop()
root.destroy() 