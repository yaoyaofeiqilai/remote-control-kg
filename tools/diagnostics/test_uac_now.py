import dxcam
import time
from PIL import Image
import subprocess
import sys

print("Testing DXGI UAC capture...")
camera = dxcam.create()
time.sleep(0.5)

print("Capture frame before UAC...")
frame1 = camera.grab()
if frame1 is not None:
    Image.fromarray(frame1).save("before_uac.png")
    print("Saved: before_uac.png")

print("\nTriggering UAC popup in 3 seconds...")
time.sleep(3)

# 触发 UAC（以管理员启动cmd，但使用 /c exit 立即退出）
subprocess.Popen(
    ['powershell', '-Command', 'Start-Process cmd -ArgumentList "/c echo UAC_TEST" -Verb runAs'],
    shell=True
)

print("Capturing during UAC (waiting 2 seconds)...")
time.sleep(2)

print("Capture frame during UAC...")
frame2 = camera.grab()
if frame2 is not None:
    Image.fromarray(frame2).save("during_uac.png")
    print("Saved: during_uac.png")
    print(f"Frame size: {frame2.shape}")
else:
    print("Failed to capture during UAC!")

camera.release()
print("\nDone! Check before_uac.png and during_uac.png")
