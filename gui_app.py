#!/usr/bin/env python3
"""
Gemini Watermark Remover - Windows GUI Tool
Giao diện đồ họa chọn ảnh và hiển thị kết quả xóa watermark Gemini.
"""

import sys
import os
import shutil
import subprocess
import json
import tempfile
import threading
import queue
import io
import struct
import time
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageGrab

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import win32clipboard
    HAS_WIN32CLIPBOARD = True
except ImportError:
    HAS_WIN32CLIPBOARD = False

# Cấu hình AppUserModelID cho Windows để ghim thanh tác vụ (Taskbar Pinning) hiển thị đúng icon và tên ứng dụng
try:
    import ctypes
    APP_ID = "gargantuax.geminiwatermarkremover.desktop.gui"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
except Exception:
    pass

# Màu sắc giao diện (Dark Theme Hiện Đại)
COLOR_BG = "#13141f"
COLOR_CARD = "#1c1e2d"
COLOR_CARD_BORDER = "#2a2d42"
COLOR_PANEL = "#171826"
COLOR_PRIMARY = "#10b981"         # Emerald Green
COLOR_PRIMARY_HOVER = "#059669"
COLOR_PRIMARY_ACTIVE = "#047857"
COLOR_TEXT_WHITE = "#f9fafb"
COLOR_TEXT_MUTED = "#9ca3af"
COLOR_TEXT_DIM = "#6b7280"
COLOR_ACCENT = "#3b82f6"
COLOR_SUCCESS = "#34d399"
COLOR_WARNING = "#f59e0b"

def setup_native_drag_drop(window, callback):
    """
    Hook WM_DROPFILES an toàn 100% trên Windows (hỗ trợ cả 32-bit và 64-bit).
    Thiết lập rõ ràng kiểu argtypes và restype của Win32 API để tránh lỗi
    Access Violation (0xC0000005) do ctypes mặc định cắt con trỏ 64-bit thành 32-bit.
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32

        hwnd = window.winfo_id()
        GWL_WNDPROC = -4
        WM_DROPFILES = 0x0233

        is_64bit = struct.calcsize("P") == 8
        LONG_PTR = ctypes.c_int64 if is_64bit else ctypes.c_long

        if is_64bit:
            GetWindowLongPtr = user32.GetWindowLongPtrW
            SetWindowLongPtr = user32.SetWindowLongPtrW
        else:
            GetWindowLongPtr = user32.GetWindowLongW
            SetWindowLongPtr = user32.SetWindowLongW

        GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
        GetWindowLongPtr.restype = LONG_PTR

        WNDPROC = ctypes.WINFUNCTYPE(LONG_PTR, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, WNDPROC]
        SetWindowLongPtr.restype = LONG_PTR

        user32.CallWindowProcW.argtypes = [LONG_PTR, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = LONG_PTR

        shell32.DragQueryFileW.argtypes = [wintypes.WPARAM, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT

        shell32.DragFinish.argtypes = [wintypes.WPARAM]
        shell32.DragFinish.restype = None

        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragAcceptFiles.restype = None

        shell32.DragAcceptFiles(hwnd, True)
        old_wndproc = GetWindowLongPtr(hwnd, GWL_WNDPROC)

        def wndproc(h_wnd, msg, w_param, l_param):
            if msg == WM_DROPFILES:
                try:
                    count = shell32.DragQueryFileW(w_param, 0xFFFFFFFF, None, 0)
                    files = []
                    buf = ctypes.create_unicode_buffer(1024)
                    for i in range(count):
                        length = shell32.DragQueryFileW(w_param, i, buf, 1024)
                        if length > 0:
                            files.append(buf.value)
                    shell32.DragFinish(w_param)
                    if files:
                        window.after(10, lambda f=files: callback(f))
                    return 0
                except Exception as e:
                    print("WM_DROPFILES error:", e)
                    try:
                        shell32.DragFinish(w_param)
                    except Exception:
                        pass
                    return 0

            return user32.CallWindowProcW(old_wndproc, h_wnd, msg, w_param, l_param)

        window._native_wndproc_ref = WNDPROC(wndproc)
        SetWindowLongPtr(hwnd, GWL_WNDPROC, window._native_wndproc_ref)
        return True
    except Exception as err:
        print("setup_native_drag_drop error:", err)
        return False

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def find_node_executable():
    # 1. Tìm node đóng gói cùng nếu có
    base_dir = get_base_dir()
    bundled_node = base_dir / "node.exe"
    if bundled_node.is_file():
        return str(bundled_node)
    
    # 2. Tìm trong PATH
    system_node = shutil.which("node")
    if system_node:
        return system_node
    
    # 3. Các đường dẫn mặc định trên Windows
    default_paths = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "node" / "node.exe",
    ]
    for p in default_paths:
        if p.is_file():
            return str(p)
    return None

def find_gwr_cli():
    search_dirs = []
    
    # 1. Thư mục PyInstaller giải nén (nếu đóng gói)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        search_dirs.append(Path(sys._MEIPASS))
    
    # 2. Thư mục chứa file thực thi (.exe hoặc .py)
    search_dirs.append(Path(__file__).resolve().parent)
    search_dirs.append(Path(sys.executable).resolve().parent)
    search_dirs.append(Path(sys.executable).resolve().parent.parent)

    # 3. Thư mục dự án đã biết
    search_dirs.append(Path("E:/dev/gemini-watermark-remover"))

    for d in search_dirs:
        candidates = [
            d / "dist" / "cli-bundle.mjs",
            d / "bin" / "gwr.mjs",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
    return None

def is_video_file(file_path):
    if not file_path:
        return False
    return Path(file_path).suffix.lower() in [".mp4", ".webm", ".mov", ".m4v", ".mkv"]

def extract_video_frame(video_path, frame_ratio=0.25):
    """
    Trích xuất một khung hình từ video để làm preview trên giao diện.
    Trả về (PIL.Image, info_dict).
    """
    if not HAS_CV2:
        return None, {}
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None, {}
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = (total_frames / fps) if fps > 0 else 0

        target_idx = max(0, min(total_frames - 1, int(total_frames * frame_ratio)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            info = {
                "width": width,
                "height": height,
                "fps": round(fps, 1),
                "duration": round(duration, 1),
                "total_frames": total_frames,
                "frame_idx": target_idx
            }
            return pil_img, info
    except Exception as e:
        print("extract_video_frame error:", e)
    return None, {}

class WatermarkRemoverApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gemini Watermark Remover — AI Watermark Removal Tool")
        self.geometry("1180x820")
        self.minsize(980, 680)
        self.configure(bg=COLOR_BG)

        # Trạng thái tệp (Ảnh / Video)
        self.input_file_path = None
        self.original_image = None
        self.cleaned_image = None
        self.processed_temp_path = None
        self.is_processing = False
        self.is_video_mode = False
        self.video_info = {}

        # Khởi tạo Node & CLI
        self.node_path = find_node_executable()
        self.gwr_cli_path = find_gwr_cli()
        self.msg_queue = queue.Queue()

        self._set_app_icon()
        self._setup_styles()
        self._build_ui()
        self._setup_drag_and_drop_and_paste()
        self._check_environment()
        self._poll_msg_queue()

    def _setup_drag_and_drop_and_paste(self):
        # Phím tắt dán Ctrl+V toàn cục
        self.bind_all("<Control-v>", lambda e: self.paste_from_clipboard())
        self.bind_all("<Control-V>", lambda e: self.paste_from_clipboard())

        # Kéo thả tệp an toàn 100% không crash trên Windows 64-bit
        setup_native_drag_drop(self, self.on_drop_files)

    def _set_app_icon(self):
        base_dir = get_base_dir()
        icon_candidates = [
            base_dir / "src" / "extension" / "assets" / "app-icon.ico",
            base_dir / "assets" / "app-icon.ico",
            base_dir / "app-icon.ico",
            Path(__file__).resolve().parent / "src" / "extension" / "assets" / "app-icon.ico",
        ]
        for icon_path in icon_candidates:
            if icon_path.is_file():
                try:
                    self.iconbitmap(str(icon_path))
                    break
                except Exception:
                    pass

        png_candidates = [
            base_dir / "src" / "extension" / "assets" / "icon-128.png",
            base_dir / "assets" / "icon-128.png",
            Path(__file__).resolve().parent / "src" / "extension" / "assets" / "icon-128.png"
        ]
        for png_path in png_candidates:
            if png_path.is_file():
                try:
                    self._app_icon_photo = ImageTk.PhotoImage(file=str(png_path))
                    self.iconphoto(True, self._app_icon_photo)
                    break
                except Exception:
                    pass

    def _poll_msg_queue(self):
        try:
            while not self.msg_queue.empty():
                msg_type, *args = self.msg_queue.get_nowait()
                if msg_type == "progress":
                    percent, frame_text = args
                    self.progressbar.config(mode="determinate", maximum=100, value=percent)
                    label = f"⏳ Đang xử lý video: {percent}%"
                    if frame_text:
                        label += f" ({frame_text})"
                    self.lbl_status.config(text=label, fg=COLOR_ACCENT)
                elif msg_type == "success":
                    cleaned_pil, output_temp_path, meta_json = args
                    self._on_removal_success(cleaned_pil, output_temp_path, meta_json)
                elif msg_type == "video_success":
                    output_video_path, cleaned_pil, meta_json = args
                    self._on_video_removal_success(output_video_path, cleaned_pil, meta_json)
                elif msg_type == "error":
                    err_msg, = args
                    self._on_removal_error(err_msg)
        except Exception as e:
            print("Queue poll error:", e)
        finally:
            self.after(50, self._poll_msg_queue)

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Cấu hình thanh tiến trình
        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor=COLOR_CARD,
            background=COLOR_PRIMARY,
            bordercolor=COLOR_CARD,
            lightcolor=COLOR_PRIMARY,
            darkcolor=COLOR_PRIMARY
        )

    def _build_ui(self):
        # 1. Header Bar
        header = tk.Frame(self, bg=COLOR_CARD, height=64, padx=20)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        # Logo & Tiêu đề
        title_box = tk.Frame(header, bg=COLOR_CARD)
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        title_lbl = tk.Label(
            title_box,
            text="✦ Gemini Watermark Remover",
            font=("Segoe UI", 13, "bold"),
            bg=COLOR_CARD,
            fg=COLOR_PRIMARY
        )
        title_lbl.pack(side=tk.LEFT, pady=18)

        sub_lbl = tk.Label(
            title_box,
            text=" |  Lossless Reverse Alpha Blending",
            font=("Segoe UI", 9),
            bg=COLOR_CARD,
            fg=COLOR_TEXT_DIM
        )
        sub_lbl.pack(side=tk.LEFT, pady=20)

        # Nhóm nút thao tác góc phải
        action_bar = tk.Frame(header, bg=COLOR_CARD)
        action_bar.pack(side=tk.RIGHT, fill=tk.Y, pady=12)

        self.btn_open = tk.Button(
            action_bar,
            text="📂  Chọn Tệp...",
            font=("Segoe UI", 9, "bold"),
            bg=COLOR_PRIMARY,
            fg=COLOR_TEXT_WHITE,
            activebackground=COLOR_PRIMARY_HOVER,
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            command=self.select_input_file
        )
        self.btn_open.pack(side=tk.LEFT, padx=4)

        self.btn_paste = tk.Button(
            action_bar,
            text="📋  Dán (Ctrl+V)",
            font=("Segoe UI", 9, "bold"),
            bg="#3b82f6",
            fg=COLOR_TEXT_WHITE,
            activebackground="#2563eb",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            command=self.paste_from_clipboard
        )
        self.btn_paste.pack(side=tk.LEFT, padx=4)

        self.btn_process = tk.Button(
            action_bar,
            text="⚡  Xóa Watermark",
            font=("Segoe UI", 9, "bold"),
            bg="#2563eb",
            fg=COLOR_TEXT_WHITE,
            activebackground="#1d4ed8",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.start_watermark_removal
        )
        self.btn_process.pack(side=tk.LEFT, padx=4)

        self.btn_save = tk.Button(
            action_bar,
            text="💾  Lưu...",
            font=("Segoe UI", 9),
            bg=COLOR_CARD_BORDER,
            fg=COLOR_TEXT_WHITE,
            activebackground="#374151",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.save_output_file
        )
        self.btn_save.pack(side=tk.LEFT, padx=4)

        self.btn_play = tk.Button(
            action_bar,
            text="▶  Phát Video",
            font=("Segoe UI", 9, "bold"),
            bg="#059669",
            fg=COLOR_TEXT_WHITE,
            activebackground="#047857",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.play_video
        )
        self.btn_play.pack(side=tk.LEFT, padx=4)

        self.btn_folder = tk.Button(
            action_bar,
            text="📁  Thư Mục",
            font=("Segoe UI", 9),
            bg=COLOR_CARD_BORDER,
            fg=COLOR_TEXT_WHITE,
            activebackground="#374151",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.open_output_folder
        )
        self.btn_folder.pack(side=tk.LEFT, padx=4)

        self.btn_copy = tk.Button(
            action_bar,
            text="📋  Copy",
            font=("Segoe UI", 9),
            bg=COLOR_CARD_BORDER,
            fg=COLOR_TEXT_WHITE,
            activebackground="#374151",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.copy_to_clipboard
        )
        self.btn_copy.pack(side=tk.LEFT, padx=4)

        # 2. Main Content Split View (2 Khung Ảnh)
        content_frame = tk.Frame(self, bg=COLOR_BG, padx=16, pady=12)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Cấu hình grid 2 cột cân xứng
        content_frame.columnconfigure(0, weight=1, uniform="col")
        content_frame.columnconfigure(1, weight=1, uniform="col")
        content_frame.rowconfigure(0, weight=1)

        # Card Trái: Ảnh Gốc
        left_card = tk.Frame(content_frame, bg=COLOR_CARD, highlightbackground=COLOR_CARD_BORDER, highlightthickness=1)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        left_header = tk.Frame(left_card, bg=COLOR_PANEL, height=36, padx=12)
        left_header.pack(fill=tk.X, side=tk.TOP)
        left_header.pack_propagate(False)

        tk.Label(left_header, text="GỐC (ORIGINAL)", font=("Segoe UI", 9, "bold"), bg=COLOR_PANEL, fg=COLOR_TEXT_MUTED).pack(side=tk.LEFT, pady=8)
        self.lbl_orig_info = tk.Label(left_header, text="Chưa có tệp", font=("Consolas", 8), bg=COLOR_PANEL, fg=COLOR_TEXT_DIM)
        self.lbl_orig_info.pack(side=tk.RIGHT, pady=8)

        self.canvas_orig = tk.Canvas(left_card, bg="#0d0e15", highlightthickness=0, cursor="hand2")
        self.canvas_orig.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.canvas_orig.bind("<Configure>", lambda e: self._redraw_original())
        self.canvas_orig.bind("<Button-1>", self._on_canvas_orig_click)

        # Card Phải: Ảnh / Video Đã Xóa Watermark
        right_card = tk.Frame(content_frame, bg=COLOR_CARD, highlightbackground=COLOR_CARD_BORDER, highlightthickness=1)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        right_header = tk.Frame(right_card, bg=COLOR_PANEL, height=36, padx=12)
        right_header.pack(fill=tk.X, side=tk.TOP)
        right_header.pack_propagate(False)

        tk.Label(right_header, text="KẾT QUẢ ĐÃ XÓA WATERMARK", font=("Segoe UI", 9, "bold"), bg=COLOR_PANEL, fg=COLOR_PRIMARY).pack(side=tk.LEFT, pady=8)
        self.lbl_clean_info = tk.Label(right_header, text="Đang chờ...", font=("Consolas", 8), bg=COLOR_PANEL, fg=COLOR_TEXT_DIM)
        self.lbl_clean_info.pack(side=tk.RIGHT, pady=8)

        self.canvas_clean = tk.Canvas(right_card, bg="#0d0e15", highlightthickness=0)
        self.canvas_clean.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.canvas_clean.bind("<Configure>", lambda e: self._redraw_cleaned())

        # Menu ngữ cảnh khi bấm chuột phải
        self.context_menu = tk.Menu(
            self,
            tearoff=0,
            bg=COLOR_CARD,
            fg=COLOR_TEXT_WHITE,
            activebackground=COLOR_PRIMARY,
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT
        )
        self.context_menu.add_command(label="📋  Dán từ Clipboard (Ctrl+V)", command=self.paste_from_clipboard)
        self.context_menu.add_command(label="📂  Chọn tệp từ máy tính...", command=self.select_input_file)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⚡  Xóa Watermark", command=self.start_watermark_removal)
        self.context_menu.add_command(label="💾  Lưu kết quả...", command=self.save_output_file)
        self.context_menu.add_command(label="📋  Copy ảnh kết quả", command=self.copy_to_clipboard)
        self.context_menu.add_command(label="📁  Mở thư mục chứa", command=self.open_output_folder)

        self.canvas_orig.bind("<Button-3>", self._show_context_menu)
        self.canvas_clean.bind("<Button-3>", self._show_context_menu)
        self.bind("<Button-3>", self._show_context_menu)

        # 3. Vùng Phóng to Chi tiết Watermark (ROI Detail Inspection)
        self.zoom_card = tk.Frame(self, bg=COLOR_CARD, height=130, highlightbackground=COLOR_CARD_BORDER, highlightthickness=1)
        self.zoom_card.pack(fill=tk.X, padx=16, pady=(0, 10))
        self.zoom_card.pack_propagate(False)

        zoom_header = tk.Frame(self.zoom_card, bg=COLOR_PANEL, height=28, padx=12)
        zoom_header.pack(fill=tk.X, side=tk.TOP)
        zoom_header.pack_propagate(False)

        tk.Label(zoom_header, text="🔍 SOI CHI TIẾT VÙNG WATERMARK (GÓC DƯỚI BÊN PHẢI - ZOOM 2X)", font=("Segoe UI", 8, "bold"), bg=COLOR_PANEL, fg=COLOR_ACCENT).pack(side=tk.LEFT, pady=5)
        self.lbl_roi_status = tk.Label(zoom_header, text="", font=("Segoe UI", 8), bg=COLOR_PANEL, fg=COLOR_TEXT_MUTED)
        self.lbl_roi_status.pack(side=tk.RIGHT, pady=5)

        zoom_body = tk.Frame(self.zoom_card, bg=COLOR_CARD, padx=12, pady=6)
        zoom_body.pack(fill=tk.BOTH, expand=True)

        # Cột Zoom Trước
        frame_zoom_before = tk.Frame(zoom_body, bg=COLOR_CARD)
        frame_zoom_before.pack(side=tk.LEFT, padx=10)
        tk.Label(frame_zoom_before, text="Trước khi xóa:", font=("Segoe UI", 8), bg=COLOR_CARD, fg=COLOR_TEXT_DIM).pack(anchor="w")
        self.lbl_roi_orig = tk.Label(frame_zoom_before, bg="#0d0e15", width=22, height=4)
        self.lbl_roi_orig.pack()

        # Mũi tên chỉ dẫn
        tk.Label(zoom_body, text="➔", font=("Segoe UI", 16), bg=COLOR_CARD, fg=COLOR_PRIMARY).pack(side=tk.LEFT, padx=15)

        # Cột Zoom Sau
        frame_zoom_after = tk.Frame(zoom_body, bg=COLOR_CARD)
        frame_zoom_after.pack(side=tk.LEFT, padx=10)
        tk.Label(frame_zoom_after, text="Sau khi xóa:", font=("Segoe UI", 8), bg=COLOR_CARD, fg=COLOR_TEXT_DIM).pack(anchor="w")
        self.lbl_roi_clean = tk.Label(frame_zoom_after, bg="#0d0e15", width=22, height=4)
        self.lbl_roi_clean.pack()

        # Khung thông tin metadata thuật toán
        self.meta_frame = tk.Frame(zoom_body, bg=COLOR_CARD)
        self.meta_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(20, 0))
        self.lbl_meta_details = tk.Label(
            self.meta_frame,
            text="Chọn ảnh hoặc video do Gemini AI tạo để bắt đầu nhận diện và loại bỏ watermark.",
            font=("Segoe UI", 9),
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MUTED,
            justify=tk.LEFT,
            wraplength=450
        )
        self.lbl_meta_details.pack(anchor="w", pady=10)

        # 4. Status Bar & Progress
        status_bar = tk.Frame(self, bg=COLOR_CARD, height=36, padx=16)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        self.lbl_status = tk.Label(
            status_bar,
            text="Sẵn sàng.",
            font=("Segoe UI", 9),
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MUTED
        )
        self.lbl_status.pack(side=tk.LEFT, pady=8)

        self.progressbar = ttk.Progressbar(
            status_bar,
            style="Custom.Horizontal.TProgressbar",
            mode="indeterminate",
            length=180
        )
        self.progressbar.pack(side=tk.RIGHT, pady=9)
        self.progressbar.pack_forget()

    def _check_environment(self):
        if not self.node_path:
            self.lbl_status.config(
                text="⚠️ Không tìm thấy Node.js trên máy! Vui lòng cài đặt Node.js để chạy bộ xử lý.",
                fg=COLOR_WARNING
            )
        elif not self.gwr_cli_path:
            self.lbl_status.config(
                text="⚠️ Không tìm thấy tệp CLI engine (gwr.mjs) trong thư mục dự án!",
                fg=COLOR_WARNING
            )

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _on_canvas_orig_click(self, event):
        if not self.original_image and not self.is_processing:
            self.select_input_file()

    def on_drop_files(self, files):
        if self.is_processing:
            messagebox.showwarning("Đang xử lý", "Hệ thống đang xử lý tệp hiện tại. Vui lòng đợi hoàn tất trước khi nạp tệp mới.")
            return

        if not files:
            return

        raw_path = files[0]
        if isinstance(raw_path, bytes):
            try:
                file_path = raw_path.decode("utf-8")
            except Exception:
                file_path = raw_path.decode("mbcs", errors="replace")
        else:
            file_path = str(raw_path)

        file_path = file_path.strip().strip('"\'')
        if os.path.isfile(file_path):
            self.load_input_file(file_path)
        else:
            messagebox.showerror("Tệp không tồn tại", f"Không thể tìm thấy tệp được kéo thả:\n{file_path}")

    def paste_from_clipboard(self):
        if self.is_processing:
            messagebox.showwarning("Đang xử lý", "Hệ thống đang xử lý tệp hiện tại. Vui lòng đợi hoàn tất trước khi dán tệp mới.")
            return

        # 1. Thử lấy ảnh trực tiếp từ clipboard (ảnh chụp màn hình, copy image từ web/app)
        try:
            clip_data = ImageGrab.grabclipboard()
            if isinstance(clip_data, Image.Image):
                temp_file = Path(tempfile.gettempdir()) / f"gwr_clipboard_{int(time.time() * 1000)}.png"
                clip_data.save(temp_file, format="PNG")
                self.lbl_status.config(text="Đã dán ảnh từ Clipboard", fg=COLOR_TEXT_WHITE)
                self.load_input_file(str(temp_file))
                return
            elif isinstance(clip_data, list):
                for p in clip_data:
                    p_str = str(p).strip().strip('"\'')
                    if os.path.isfile(p_str):
                        self.lbl_status.config(text=f"Đã dán tệp từ Clipboard: {Path(p_str).name}", fg=COLOR_TEXT_WHITE)
                        self.load_input_file(p_str)
                        return
        except Exception as e:
            print("ImageGrab clipboard error:", e)

        # 2. Thử đọc danh sách tệp từ win32clipboard (CF_HDROP)
        if HAS_WIN32CLIPBOARD:
            try:
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                    files = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
                    win32clipboard.CloseClipboard()
                    if files:
                        for f in files:
                            f_str = str(f).strip().strip('"\'')
                            if os.path.isfile(f_str):
                                self.load_input_file(f_str)
                                return
                else:
                    win32clipboard.CloseClipboard()
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass

        # 3. Thử đọc đường dẫn văn bản từ clipboard (vd: copy text đường dẫn C:\...\video.mp4)
        try:
            raw_text = self.clipboard_get()
            if raw_text:
                for line in raw_text.splitlines():
                    cleaned_line = line.strip().strip('"\'')
                    if os.path.isfile(cleaned_line):
                        self.lbl_status.config(text=f"Đã mở tệp từ đường dẫn: {Path(cleaned_line).name}", fg=COLOR_TEXT_WHITE)
                        self.load_input_file(cleaned_line)
                        return
        except Exception:
            pass

        # 4. Nếu không có gì hợp lệ
        self.lbl_status.config(text="⚠️ Clipboard không chứa ảnh hoặc đường dẫn tệp hợp lệ.", fg=COLOR_WARNING)
        messagebox.showinfo(
            "Dán từ Clipboard (Ctrl+V)",
            "Clipboard hiện không chứa ảnh, video hoặc đường dẫn tệp hợp lệ.\n\n"
            "Các cách dán nhanh:\n"
            "• Chụp màn hình (Win + Shift + S) rồi nhấn Ctrl+V\n"
            "• Chuột phải Copy ảnh từ trình duyệt rồi nhấn Ctrl+V\n"
            "• Copy tệp từ Windows Explorer (Ctrl+C) rồi nhấn Ctrl+V\n"
            "• Copy đường dẫn tệp text rồi nhấn Ctrl+V"
        )

    def select_input_file(self):
        if self.is_processing:
            return
        
        file_path = filedialog.askopenfilename(
            title="Chọn ảnh hoặc video cần xóa watermark",
            filetypes=[
                ("Tất cả định dạng hỗ trợ (Ảnh & Video)", "*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.webm;*.mov;*.m4v"),
                ("Video MP4 / WebM / MOV", "*.mp4;*.webm;*.mov;*.m4v"),
                ("Hình ảnh PNG / JPEG / WebP", "*.png;*.jpg;*.jpeg;*.webp"),
                ("Mọi tệp", "*.*")
            ]
        )
        if not file_path:
            return

        self.load_input_file(file_path)

    def load_input_file(self, file_path):
        try:
            self.input_file_path = file_path
            self.cleaned_image = None
            self.processed_temp_path = None

            if is_video_file(file_path):
                self.is_video_mode = True
                pil_img, info = extract_video_frame(file_path, frame_ratio=0.25)
                if not pil_img:
                    messagebox.showerror("Lỗi đọc video", "Không thể trích xuất khung hình từ video để xem trước.\nVui lòng kiểm tra lại định dạng tệp.")
                    return

                self.original_image = pil_img
                self.video_info = info

                w = info.get("width", pil_img.width)
                h = info.get("height", pil_img.height)
                fps = info.get("fps", 24)
                dur = info.get("duration", 0)
                self.lbl_orig_info.config(text=f"🎬 {Path(file_path).name} ({w}×{h} • {fps}fps • {dur}s)")
                self.lbl_clean_info.config(text="Đang chờ xử lý video...")
                self.btn_save.config(text="💾  Lưu Video...")
            else:
                self.is_video_mode = False
                self.video_info = {}
                img = Image.open(file_path)
                try:
                    from PIL import ImageOps
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                self.original_image = img

                w, h = img.size
                self.lbl_orig_info.config(text=f"🖼️ {Path(file_path).name} ({w}×{h})")
                self.lbl_clean_info.config(text="Đang chờ xử lý...")
                self.btn_save.config(text="💾  Lưu Ảnh...")

            self.btn_open.config(state=tk.NORMAL)
            self.btn_paste.config(state=tk.NORMAL)
            self.btn_process.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.DISABLED)
            self.btn_play.config(state=tk.DISABLED)
            self.btn_folder.config(state=tk.DISABLED)
            self.btn_copy.config(state=tk.DISABLED)

            self._redraw_original()
            self._clear_cleaned()
            self._clear_roi()

            file_type_label = "video" if self.is_video_mode else "ảnh"
            self.lbl_status.config(text=f"Đã mở {file_type_label}: {Path(file_path).name}", fg=COLOR_TEXT_WHITE)

            # Tự động thực hiện xóa watermark ngay khi mở tệp
            self.start_watermark_removal()
        except Exception as err:
            messagebox.showerror("Lỗi mở tệp", f"Không thể đọc tệp:\n{str(err)}")

    def start_watermark_removal(self):
        if not self.original_image or self.is_processing:
            return
        if not self.node_path or not self.gwr_cli_path:
            messagebox.showerror("Thiếu môi trường", "Chưa sẵn sàng Node.js hoặc CLI engine để xử lý.")
            return

        self.is_processing = True
        self.btn_open.config(state=tk.DISABLED)
        self.btn_paste.config(state=tk.DISABLED)
        self.btn_process.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_play.config(state=tk.DISABLED)
        self.btn_folder.config(state=tk.DISABLED)
        self.btn_copy.config(state=tk.DISABLED)

        if self.is_video_mode:
            self.progressbar.config(mode="determinate", maximum=100, value=0)
            self.progressbar.pack(side=tk.RIGHT, pady=9)
            self.lbl_status.config(text="⏳ Đang khởi tạo bộ giải mã Video AI...", fg=COLOR_ACCENT)
        else:
            self.progressbar.config(mode="indeterminate")
            self.progressbar.pack(side=tk.RIGHT, pady=9)
            self.progressbar.start(10)
            self.lbl_status.config(text="⏳ Đang phân tích thuật toán Reverse Alpha Blending...", fg=COLOR_ACCENT)

        thread = threading.Thread(target=self._run_removal_worker, daemon=True)
        thread.start()

    def _run_removal_worker(self):
        temp_dir = tempfile.mkdtemp(prefix="gwr_gui_")

        if self.is_video_mode:
            self._run_video_removal_worker(temp_dir)
            return

        input_raw_path = os.path.join(temp_dir, "input.raw")
        output_raw_path = os.path.join(temp_dir, "output.raw")
        output_temp_path = os.path.join(temp_dir, "cleaned_output.png")

        try:
            # 1. Đọc và chuyển đổi ảnh sang RGBA bằng Pillow
            orig_pil = Image.open(self.input_file_path)
            try:
                from PIL import ImageOps
                orig_pil = ImageOps.exif_transpose(orig_pil)
            except Exception:
                pass

            rgba_img = orig_pil.convert("RGBA")
            w, h = rgba_img.size

            # Ghi file nhị phân raw-rgba: 4 bytes width, 4 bytes height, tiếp nối w*h*4 raw bytes
            header = struct.pack("<II", w, h)
            with open(input_raw_path, "wb") as f:
                f.write(header + rgba_img.tobytes())

            cmd = [
                self.node_path,
                self.gwr_cli_path,
                "remove",
                input_raw_path,
                "--output",
                output_raw_path,
                "--decoder",
                "raw-rgba",
                "--encoder",
                "raw-rgba",
                "--overwrite",
                "--json"
            ]

            # 2. Cấu hình biến môi trường và thư mục làm việc
            env = os.environ.copy()
            node_paths = [
                str(Path("E:/dev/gemini-watermark-remover/node_modules")),
                str(get_base_dir() / "node_modules"),
                str(Path(sys.executable).parent / "node_modules")
            ]
            if env.get("NODE_PATH"):
                node_paths.append(env["NODE_PATH"])
            env["NODE_PATH"] = os.pathsep.join([p for p in node_paths if os.path.exists(p)])

            cwd_path = str(Path(self.gwr_cli_path).resolve().parent.parent) if self.gwr_cli_path else str(get_base_dir())
            process = subprocess.run(
                cmd,
                cwd=cwd_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )

            if process.returncode != 0:
                err_msg = process.stderr.strip() or process.stdout.strip() or f"Mã thoát: {process.returncode}"
                self.msg_queue.put(("error", err_msg))
                return

            # 3. Đọc JSON siêu dữ liệu đầu ra
            stdout_clean = process.stdout.strip()
            meta_json = None
            if stdout_clean:
                try:
                    lines = stdout_clean.splitlines()
                    for line in reversed(lines):
                        line = line.strip()
                        if line.startswith("{") and line.endswith("}"):
                            parsed = json.loads(line)
                            meta_json = parsed.get("meta") if "meta" in parsed else parsed
                            break
                except Exception:
                    pass

            # 4. Kiểm tra tệp kết quả raw và chuyển thành ảnh PIL
            if not os.path.exists(output_raw_path):
                self.msg_queue.put(("error", "Lệnh chạy xong nhưng không tạo ra tệp ảnh kết quả."))
                return

            with open(output_raw_path, "rb") as f:
                raw_data = f.read()

            if len(raw_data) < 8:
                self.msg_queue.put(("error", "Dữ liệu trả về từ engine không hợp lệ."))
                return

            out_w, out_h = struct.unpack("<II", raw_data[:8])
            expected_data_len = out_w * out_h * 4
            if len(raw_data) < 8 + expected_data_len:
                self.msg_queue.put(("error", f"Dữ liệu ảnh không đủ ({len(raw_data)} / {8 + expected_data_len} bytes)."))
                return

            pixel_bytes = raw_data[8:8 + expected_data_len]
            cleaned_pil = Image.frombytes("RGBA", (out_w, out_h), pixel_bytes)

            # Lưu ảnh PNG kết quả
            cleaned_pil.save(output_temp_path, format="PNG")

            self.msg_queue.put(("success", cleaned_pil, output_temp_path, meta_json))

        except subprocess.TimeoutExpired:
            self.msg_queue.put(("error", "Hết thời gian chờ (quá 60 giây)."))
        except Exception as e:
            self.msg_queue.put(("error", str(e)))

    def _run_video_removal_worker(self, temp_dir):
        try:
            in_path = Path(self.input_file_path)
            output_video_path = os.path.join(temp_dir, f"{in_path.stem}_cleaned{in_path.suffix}")

            cmd = [
                self.node_path,
                self.gwr_cli_path,
                "remove",
                str(in_path),
                "--output",
                output_video_path,
                "--allow-low-confidence",
                "--overwrite",
                "--json"
            ]

            env = os.environ.copy()
            node_paths = [
                str(Path("E:/dev/gemini-watermark-remover/node_modules")),
                str(get_base_dir() / "node_modules"),
                str(Path(sys.executable).parent / "node_modules"),
                str(Path(self.gwr_cli_path).resolve().parent.parent / "node_modules") if self.gwr_cli_path else ""
            ]
            if env.get("NODE_PATH"):
                node_paths.append(env["NODE_PATH"])
            env["NODE_PATH"] = os.pathsep.join([p for p in node_paths if os.path.exists(p)])

            cwd_path = str(Path(self.gwr_cli_path).resolve().parent.parent) if self.gwr_cli_path else str(get_base_dir())
            process = subprocess.Popen(
                cmd,
                cwd=cwd_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            stdout_lines = []
            def read_stdout():
                for line in process.stdout:
                    stdout_lines.append(line)
            t_out = threading.Thread(target=read_stdout, daemon=True)
            t_out.start()

            stderr_lines = []
            for line in process.stderr:
                line_str = line.strip()
                if not line_str:
                    continue
                stderr_lines.append(line_str)
                if line_str.startswith("[video]"):
                    parts = line_str.split()
                    if len(parts) >= 2 and "%" in parts[1]:
                        try:
                            pct = int(parts[1].replace("%", ""))
                            frame_info = " ".join(parts[2:]) if len(parts) > 2 else ""
                            self.msg_queue.put(("progress", pct, frame_info))
                        except ValueError:
                            pass

            process.wait()
            t_out.join(timeout=5)

            if process.returncode != 0:
                filtered_stderr = [l for l in stderr_lines if not l.strip().startswith("[video]")]
                raw_err = "\n".join(filtered_stderr).strip() or "".join(stdout_lines).strip() or f"Mã thoát: {process.returncode}"
                if "视频水印检测置信度偏低" in raw_err:
                    err_msg = "Độ tin cậy nhận diện watermark thấp (video có thể đã sạch hoặc không chứa watermark Gemini).\nBạn có thể thử lại với video gốc."
                else:
                    err_msg = raw_err
                self.msg_queue.put(("error", err_msg))
                return

            if not os.path.exists(output_video_path):
                self.msg_queue.put(("error", "Lệnh chạy xong nhưng không tạo ra tệp video kết quả."))
                return

            stdout_clean = "".join(stdout_lines).strip()
            meta_json = None
            if stdout_clean:
                try:
                    for line in reversed(stdout_clean.splitlines()):
                        line = line.strip()
                        if line.startswith("{") and line.endswith("}"):
                            parsed = json.loads(line)
                            meta_json = parsed.get("meta") if "meta" in parsed else parsed
                            break
                except Exception:
                    pass

            cleaned_pil, _ = extract_video_frame(output_video_path, frame_ratio=0.25)

            self.msg_queue.put(("video_success", output_video_path, cleaned_pil, meta_json))

        except Exception as e:
            self.msg_queue.put(("error", str(e)))

    def _on_removal_success(self, cleaned_pil, output_temp_path, meta_json):
        self.is_processing = False
        self.progressbar.stop()
        self.progressbar.pack_forget()

        self.btn_open.config(state=tk.NORMAL)
        self.btn_paste.config(state=tk.NORMAL)
        self.btn_process.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.NORMAL)
        self.btn_copy.config(state=tk.NORMAL)
        self.btn_folder.config(state=tk.NORMAL)
        self.btn_play.config(state=tk.DISABLED)

        self.cleaned_image = cleaned_pil
        self.processed_temp_path = output_temp_path

        w, h = cleaned_pil.size
        self.lbl_clean_info.config(text=f"Hoàn thành ({w}×{h})", fg=COLOR_PRIMARY)
        self._redraw_cleaned()
        self._update_roi_view()

        # Phân tích thông tin chi tiết
        msg = "✅ Xóa watermark thành công!"
        detail_lines = []
        if meta_json:
            cand = meta_json.get("candidate")
            dur = meta_json.get("durationMs", 0)
            if cand:
                c_size = cand.get("size", "N/A")
                c_score = cand.get("finalScore", 0)
                detail_lines.append(f"Watermark: {c_size}px (Điểm tin cậy: {c_score:.2f})")
                detail_lines.append(f"Vị trí: x={cand.get('x')}, y={cand.get('y')}")
            if dur:
                detail_lines.append(f"Thời gian: {dur}ms")

        if detail_lines:
            self.lbl_meta_details.config(text=" • ".join(detail_lines), fg=COLOR_SUCCESS)
        else:
            self.lbl_meta_details.config(text="Thuật toán Reverse Alpha Blending đã khôi phục pixel gốc.", fg=COLOR_TEXT_WHITE)

        self.lbl_status.config(text=msg, fg=COLOR_SUCCESS)

    def _on_video_removal_success(self, output_video_path, cleaned_pil, meta_json):
        self.is_processing = False
        self.progressbar.stop()
        self.progressbar.pack_forget()

        self.btn_open.config(state=tk.NORMAL)
        self.btn_paste.config(state=tk.NORMAL)
        self.btn_process.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.NORMAL)
        self.btn_play.config(state=tk.NORMAL)
        self.btn_folder.config(state=tk.NORMAL)
        self.btn_copy.config(state=tk.NORMAL if cleaned_pil else tk.DISABLED)

        self.cleaned_image = cleaned_pil
        self.processed_temp_path = output_video_path

        if cleaned_pil:
            w, h = cleaned_pil.size
            self.lbl_clean_info.config(text=f"Hoàn thành ({w}×{h} • Video MP4)", fg=COLOR_PRIMARY)
            self._redraw_cleaned()
            self._update_roi_view()

        msg = "✅ Xóa watermark video thành công!"
        detail_lines = []
        if meta_json:
            status_text = meta_json.get("status")
            backend = meta_json.get("actualDenoiseBackend") or meta_json.get("denoiseBackend")
            if status_text:
                import re
                m_frame = re.search(r"已处理\s*(\d+)\s*帧", status_text)
                m_audio = re.search(r"音频已保留[：:]\s*([a-zA-Z0-9]+)", status_text)
                if m_frame:
                    frames_count = m_frame.group(1)
                    audio_codec = m_audio.group(1).upper() if m_audio else "Gốc"
                    detail_lines.append(f"Đã xử lý {frames_count} frames")
                    detail_lines.append(f"Âm thanh: {audio_codec}")
                else:
                    detail_lines.append(status_text)
            elif backend:
                detail_lines.append(f"Backend: {backend}")

        if detail_lines:
            self.lbl_meta_details.config(text=" • ".join(detail_lines), fg=COLOR_SUCCESS)
        else:
            self.lbl_meta_details.config(text="Đã xóa watermark trên từng frame của video và giữ nguyên âm thanh.", fg=COLOR_TEXT_WHITE)

        self.lbl_status.config(text=msg, fg=COLOR_SUCCESS)

    def _on_removal_error(self, err_msg):
        self.is_processing = False
        self.progressbar.stop()
        self.progressbar.pack_forget()

        self.btn_open.config(state=tk.NORMAL)
        self.btn_paste.config(state=tk.NORMAL)
        self.btn_process.config(state=tk.NORMAL)
        self.lbl_status.config(text=f"❌ Thất bại: {err_msg}", fg="#ef4444")
        messagebox.showerror("Lỗi xử lý", f"Quá trình xóa watermark gặp sự cố:\n\n{err_msg}")

    def _update_roi_view(self):
        """Cắt góc dưới cùng bên phải và phóng to để người dùng thấy rõ độ sạch"""
        if not self.original_image or not self.cleaned_image:
            return

        w, h = self.original_image.size
        crop_size = min(160, w // 2, h // 2)
        if crop_size <= 0:
            return

        # Cắt ROI góc dưới cùng bên phải
        box = (w - crop_size, h - crop_size, w, h)
        roi_orig = self.original_image.crop(box)
        roi_clean = self.cleaned_image.crop(box)

        # Zoom lên kích thước 90x90
        disp_size = (150, 75)
        roi_orig_thumb = roi_orig.resize(disp_size, Image.Resampling.LANCZOS)
        roi_clean_thumb = roi_clean.resize(disp_size, Image.Resampling.LANCZOS)

        self._tk_roi_orig = ImageTk.PhotoImage(roi_orig_thumb)
        self._tk_roi_clean = ImageTk.PhotoImage(roi_clean_thumb)

        self.lbl_roi_orig.config(image=self._tk_roi_orig, text="", width=disp_size[0], height=disp_size[1])
        self.lbl_roi_clean.config(image=self._tk_roi_clean, text="", width=disp_size[0], height=disp_size[1])

    def _clear_roi(self):
        self.lbl_roi_orig.config(image="", text="[Trống]", width=22, height=4)
        self.lbl_roi_clean.config(image="", text="[Trống]", width=22, height=4)
        self.lbl_meta_details.config(
            text="Chọn ảnh hoặc video do Gemini AI tạo để bắt đầu nhận diện và loại bỏ watermark.",
            fg=COLOR_TEXT_MUTED
        )

    def _clear_cleaned(self):
        self.canvas_clean.delete("all")
        self.lbl_clean_info.config(text="Đang chờ...", fg=COLOR_TEXT_DIM)
        self._redraw_cleaned()

    def _fit_image_to_canvas(self, pil_img, canvas):
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw <= 10 or ch <= 10 or not pil_img:
            return None

        iw, ih = pil_img.size
        ratio = min((cw - 12) / iw, (ch - 12) / ih)
        target_w = max(1, int(iw * ratio))
        target_h = max(1, int(ih * ratio))

        resized = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(resized)

        offset_x = (cw - target_w) // 2
        offset_y = (ch - target_h) // 2

        canvas.delete("all")
        canvas.create_image(offset_x, offset_y, anchor="nw", image=tk_img)
        return tk_img

    def _draw_empty_placeholder(self, canvas, title, subtitle, details):
        canvas.delete("all")
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw <= 20 or ch <= 20:
            return

        pad = 18
        # Khung viền nét đứt phong cách kéo thả hiện đại
        canvas.create_rectangle(
            pad, pad, cw - pad, ch - pad,
            outline=COLOR_CARD_BORDER,
            width=2,
            dash=(6, 6)
        )

        mid_x = cw // 2
        mid_y = ch // 2

        # Tiêu đề
        canvas.create_text(
            mid_x, mid_y - 28,
            text=title,
            font=("Segoe UI", 12, "bold"),
            fill=COLOR_PRIMARY,
            justify=tk.CENTER
        )

        # Hướng dẫn phụ
        canvas.create_text(
            mid_x, mid_y + 4,
            text=subtitle,
            font=("Segoe UI", 10),
            fill=COLOR_TEXT_WHITE,
            justify=tk.CENTER
        )

        # Thông tin định dạng
        canvas.create_text(
            mid_x, mid_y + 32,
            text=details,
            font=("Segoe UI", 8),
            fill=COLOR_TEXT_DIM,
            justify=tk.CENTER
        )

    def _redraw_original(self):
        if self.original_image:
            self.canvas_orig.config(cursor="")
            self._tk_orig = self._fit_image_to_canvas(self.original_image, self.canvas_orig)
        else:
            self.canvas_orig.config(cursor="hand2")
            self._draw_empty_placeholder(
                self.canvas_orig,
                title="📥  KÉO THẢ TỆP VÀO ĐÂY",
                subtitle="Hoặc nhấn Ctrl+V để dán ảnh / video / đường dẫn",
                details="Nhấp chuột để chọn tệp • Hỗ trợ: PNG, JPG, WEBP, MP4, WebM, MOV..."
            )

    def _redraw_cleaned(self):
        if self.cleaned_image:
            self._tk_clean = self._fit_image_to_canvas(self.cleaned_image, self.canvas_clean)
        else:
            self._draw_empty_placeholder(
                self.canvas_clean,
                title="⚡  KẾT QUẢ ĐÃ XÓA WATERMARK",
                subtitle="Tự động nhận diện & loại bỏ watermark Gemini",
                details="Khôi phục pixel nguyên bản bằng Reverse Alpha Blending"
            )

    def save_output_file(self):
        if not self.processed_temp_path or not self.input_file_path:
            return

        orig_path = Path(self.input_file_path)

        if self.is_video_mode:
            default_name = f"{orig_path.stem}_cleaned{orig_path.suffix}"
            save_path = filedialog.asksaveasfilename(
                title="Lưu video đã xóa watermark",
                initialfile=default_name,
                filetypes=[
                    ("MP4 Video", "*.mp4"),
                    ("WebM Video", "*.webm"),
                    ("QuickTime Video", "*.mov"),
                    ("Tất cả tệp", "*.*")
                ]
            )
            if not save_path:
                return

            try:
                shutil.copy2(self.processed_temp_path, save_path)
                self.lbl_status.config(text=f"💾 Đã lưu thành công: {Path(save_path).name}", fg=COLOR_SUCCESS)
                messagebox.showinfo("Lưu thành công", f"Video đã được lưu tại:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Lỗi lưu file", f"Không thể lưu video:\n{str(e)}")
            return

        default_name = f"{orig_path.stem}_cleaned{orig_path.suffix if orig_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp'] else '.png'}"

        save_path = filedialog.asksaveasfilename(
            title="Lưu ảnh đã xóa watermark",
            initialfile=default_name,
            filetypes=[
                ("PNG Image", "*.png"),
                ("JPEG Image", "*.jpg"),
                ("WebP Image", "*.webp")
            ]
        )
        if not save_path:
            return

        try:
            self.cleaned_image.save(save_path)
            self.lbl_status.config(text=f"💾 Đã lưu thành công: {Path(save_path).name}", fg=COLOR_SUCCESS)
            messagebox.showinfo("Lưu thành công", f"Ảnh đã được lưu tại:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Lỗi lưu file", f"Không thể lưu ảnh:\n{str(e)}")

    def play_video(self):
        target = self.processed_temp_path
        if not target or not os.path.exists(target):
            messagebox.showwarning("Chưa có video", "Chưa có video kết quả để phát.")
            return
        try:
            os.startfile(target)
        except Exception as e:
            messagebox.showerror("Lỗi phát video", f"Không thể mở video:\n{str(e)}")

    def open_output_folder(self):
        target = self.processed_temp_path or self.input_file_path
        if not target or not os.path.exists(target):
            return
        try:
            subprocess.run(["explorer", f"/select,{os.path.normpath(target)}"], check=False)
        except Exception as e:
            messagebox.showerror("Lỗi mở thư mục", f"Không thể mở thư mục:\n{str(e)}")

    def copy_to_clipboard(self):
        if not self.cleaned_image:
            return

        if not HAS_WIN32CLIPBOARD:
            messagebox.showwarning("Không hỗ trợ", "Thư viện pywin32 chưa sẵn sàng để copy ảnh vào clipboard.")
            return

        try:
            output = io.BytesIO()
            # Windows Clipboard cần DIB (Device Independent Bitmap), bỏ qua 14 bytes header BMP
            rgb_img = self.cleaned_image.convert("RGB")
            rgb_img.save(output, "BMP")
            data = output.getvalue()[14:]
            output.close()

            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()

            clip_text = "frame video" if self.is_video_mode else "ảnh"
            self.lbl_status.config(text=f"📋 Đã sao chép {clip_text} vào Clipboard! Bạn có thể dán (Ctrl+V) ngay.", fg=COLOR_SUCCESS)
        except Exception as e:
            messagebox.showerror("Lỗi Clipboard", f"Không thể copy vào clipboard:\n{str(e)}")

def main():
    app = WatermarkRemoverApp()
    app.mainloop()

if __name__ == "__main__":
    main()
