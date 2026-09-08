#!/usr/bin/env python3
"""
E2E Test cho GUI Gemini Watermark Remover
Tự động mở GUI, nạp ảnh mẫu, chạy xóa watermark và chụp ảnh màn hình lưu vào docs/gui-preview.png
"""

import sys
import os
import time
from pathlib import Path
from PIL import Image
import mss

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from gui_app import WatermarkRemoverApp

def run_e2e():
    print("==================================================")
    print("  BẮT ĐẦU TEST E2E GUI GEMINI WATERMARK REMOVER   ")
    print("==================================================")

    test_input_path = ROOT_DIR / "test-input.png"
    if not test_input_path.is_file():
        print(f"❌ Không tìm thấy file test {test_input_path}")
        sys.exit(1)

    print(f"➜ Nạp ảnh test: {test_input_path}")

    # Khởi tạo GUI
    app = WatermarkRemoverApp()
    
    # Đặt vị trí cửa sổ ở màn hình chính
    app.geometry("1180x820+100+100")
    app.lift()
    app.attributes("-topmost", True)
    app.after(500, lambda: app.attributes("-topmost", False))
    app.update()

    # Nạp ảnh và kích hoạt xóa watermark
    print("➜ Gọi app.load_input_file()...")
    app.load_input_file(str(test_input_path))

    # Đợi quá trình xử lý hoàn thành
    max_wait_seconds = 30
    start_time = time.time()
    print("➜ Đang chờ tiến trình xóa watermark hoàn tất...")
    
    while app.is_processing and (time.time() - start_time) < max_wait_seconds:
        app.update()
        time.sleep(0.1)

    app.update()
    time.sleep(1.0) # Đợi render hoàn tất
    app.update()

    if app.is_processing:
        print("❌ Quá thời gian chờ (Timeout)!")
        app.destroy()
        sys.exit(1)

    if not app.cleaned_image:
        print("❌ app.cleaned_image là None sau khi xử lý!")
        app.destroy()
        sys.exit(1)

    print(f"✔ Xử lý thành công! Kích thước ảnh kết quả: {app.cleaned_image.size}")

    # Chụp ảnh màn hình cửa sổ GUI bằng PrintWindow (chụp trực tiếp từ Window DC)
    print("➜ Tiến hành chụp ảnh màn hình cửa sổ GUI...")
    import ctypes, win32gui, win32ui, win32con

    hwnd = ctypes.windll.user32.GetAncestor(app.winfo_id(), 2) # GA_ROOT = 2
    left, top, right, bot = win32gui.GetWindowRect(hwnd)
    win_w = right - left
    win_h = bot - top

    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, win_w, win_h)
    saveDC.SelectObject(saveBitMap)

    ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    screenshot_img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)

    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)

    # Lưu vào docs/gui-preview.png
    docs_dir = ROOT_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = docs_dir / "gui-preview.png"
    screenshot_img.save(screenshot_path)
    print(f"✔ Đã lưu ảnh chụp màn hình E2E tại: {screenshot_path}")

    app.destroy()
    print("\n🎉 TEST E2E HOÀN TẤT THÀNH CÔNG!")

if __name__ == "__main__":
    run_e2e()
