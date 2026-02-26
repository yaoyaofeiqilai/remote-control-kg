import time
import ctypes
from input_sender import get_input_sender

def test_uac_mouse_move():
    sender = get_input_sender()
    
    print("=== 鼠标移动测试 (DPI 感知版) ===")
    print(f"检测到的物理屏幕尺寸: {sender.screen_width}x{sender.screen_height}")
    
    print("请在 3 秒内将鼠标移动到一个普通窗口上...")
    time.sleep(3)
    
    start_x, start_y = sender.get_mouse_pos()
    print(f"初始位置: ({start_x}, {start_y})")
    
    move_x, move_y = 100, 100
    print(f"尝试相对移动 ({move_x}, {move_y})...")
    
    # 执行移动
    sender.move_relative(move_x, move_y)
    time.sleep(0.5)
    
    end_x, end_y = sender.get_mouse_pos()
    print(f"移动后位置: ({end_x}, {end_y})")
    
    dx = end_x - start_x
    dy = end_y - start_y
    print(f"实际位移: ({dx}, {dy})")
    
    # 允许 5 像素的误差（考虑到可能的鼠标微动）
    if abs(dx - move_x) <= 5 and abs(dy - move_y) <= 5:
        print("✅ 测试通过: 鼠标移动正常")
    else:
        print("❌ 测试失败: 位移不匹配")
        print(f"  期望位移: ({move_x}, {move_y})")
        print(f"  实际位移: ({dx}, {dy})")
        
    print("\n提示: 如果实际位移与期望位移成比例差异（如 1.25 倍或 1.5 倍），则是 DPI 缩放问题。")

if __name__ == "__main__":
    try:
        test_uac_mouse_move()
    except Exception as e:
        print(f"❌ 发生错误: {e}")
