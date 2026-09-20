import pyautogui
import keyboard
import win32gui
import time
from threading import Thread, Event
import sys
import signal

# 安全设置，防止鼠标失控
pyautogui.FAILSAFE = True
# 设置操作间隔
pyautogui.PAUSE = 0.5  # 每个操作之间的默认等待时间

class AutoClicker:
    def __init__(self):
        self.running = False
        self.stop_event = Event()
        self.target_window = None
        self.last_action_time = time.time()
        self.current_action = "无"
        
        # 添加信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        Thread(target=self.monitor_thread).start()
        
    def signal_handler(self, signum, frame):
        """处理退出信号"""
        print("\n收到退出信号，正在停止...")
        self.stop()
        
    def is_target_window_active(self):
        """检查目标窗口是否处于活动状态"""
        if not self.target_window:
            return False
        return win32gui.GetForegroundWindow() == self.target_window
    
    def wait_for_button(self, image_path1, image_path2, timeout=10, confidence=0.5):
        """等待按钮出现（检查两种状态）"""
        start_time = time.time()
        last_log_time = start_time
        while time.time() - start_time < timeout:
            try:
                # 每秒输出一次等待时间
                current_time = time.time()
                if current_time - last_log_time >= 1:
                    elapsed = current_time - start_time
                    print(f"已等待 {elapsed:.1f} 秒...")
                    last_log_time = current_time
                
                # 尝试匹配普通状态
                button_location = pyautogui.locateOnScreen(image_path1, confidence=confidence)
                if button_location:
                    print(f"找到普通状态按钮，位置: {button_location}")
                    return button_location
                
                # 尝试匹配悬停状态
                button_location = pyautogui.locateOnScreen(image_path2, confidence=confidence)
                if button_location:
                    print(f"找到悬停状态按钮，位置: {button_location}")
                    return button_location
                
            except Exception as e:
                pass
            time.sleep(0.1)
            if self.stop_event.is_set():
                return None
        print(f"等待超时 ({timeout} 秒)")
        return None
    
    def verify_click_result(self, button_image, timeout=3, confidence=0.5):
        """验证点击后的界面变化"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                if pyautogui.locateOnScreen(button_image, confidence=confidence):
                    return True
            except:
                pass
            time.sleep(0.1)
        return False

    def update_status(self, action):
        """更新当前动作和时间"""
        self.current_action = action
        self.last_action_time = time.time()

    def monitor_thread(self):
        """监控线程，显示程序运行状态"""
        while True:
            if self.running:
                elapsed = time.time() - self.last_action_time
                if elapsed > 2:  # 如果超过2秒没有动作，显示警告
                    print(f"\n警告: 当前动作 [{self.current_action}] 已经 {elapsed:.1f} 秒没有响应")
            time.sleep(1)

    def click_sequence(self):
        """执行点击序列"""
        while not self.stop_event.is_set():
            try:
                # 1. 点击全选按钮
                print("\n点击全选按钮 (240, 135)")
                pyautogui.click(240, 135)
                if self.stop_event.is_set(): break
                time.sleep(0.05)
                
                # 2. 点击更多按钮
                print("点击更多按钮 (434, 135)")
                pyautogui.click(434, 135)
                if self.stop_event.is_set(): break
                time.sleep(0.1)
                
                # 3. 点击删除选项
                print("点击删除选项 (460, 276)")
                pyautogui.click(460, 276)
                if self.stop_event.is_set(): break
                time.sleep(0.2)
                
                # 4. 按End键到底部
                print("按End键到底部")
                keyboard.press_and_release('end')
                if self.stop_event.is_set(): break
                time.sleep(0.4)
                
                # 5. 点击确定按钮
                print("点击确定按钮 (786, 640)")
                pyautogui.click(786, 640)
                if self.stop_event.is_set(): break
                time.sleep(0.3)
                
                # 6. 等待并点击关闭按钮
                print("\n等待关闭按钮出现...")
                if self.wait_for_button('close_button_normal.png', 'close_button_hover.png', timeout=5, confidence=0.2):
                    print("检测到关闭按钮，点击固定坐标 (864, 212)")
                    pyautogui.click(864, 212)
                    time.sleep(0.3)
                else:
                    print("未找到关闭按钮，跳过")
                    time.sleep(0.2)
                
            except Exception as e:
                print(f"操作出错: {e}")
                if self.stop_event.is_set(): break
                time.sleep(0.3)
        
        print("点击序列已停止")

    def start(self):
        """开始自动点击"""
        if not self.running:
            self.target_window = win32gui.GetForegroundWindow()
            self.running = True
            self.stop_event.clear()
            Thread(target=self.click_sequence).start()
            print("自动操作已启动")

    def stop(self):
        """停止自动点击"""
        self.running = False
        self.stop_event.set()
        print("自动操作已停止")

def main():
    clicker = AutoClicker()
    
    # 设置热键
    keyboard.add_hotkey('f9', clicker.start)   # F9 开始
    keyboard.add_hotkey('f10', clicker.stop)   # F10 停止
    keyboard.add_hotkey('ctrl+alt+q', lambda: sys.exit(0))  # 修改退出逻辑
    
    print("自动操作脚本已启动")
    print("按 F9 开始")
    print("按 F10 停止")
    print("按 Ctrl+Alt+Q 退出程序")
    
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n程序已退出")
        sys.exit(0)

if __name__ == "__main__":
    main() 