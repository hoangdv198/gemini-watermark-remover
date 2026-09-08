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
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

try:
    import win32clipboard
    HAS_WIN32CLIPBOARD = True
except ImportError:
    HAS_WIN32CLIPBOARD = False

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
            d / "bin" / "gwr.mjs",
            d / "dist" / "cli-bundle.mjs",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
    return None

class WatermarkRemoverApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gemini Watermark Remover — AI Watermark Removal Tool")
        self.geometry("1180x820")
        self.minsize(980, 680)
        self.configure(bg=COLOR_BG)

        # Trạng thái ảnh
        self.input_file_path = None
        self.original_image = None
        self.cleaned_image = None
        self.processed_temp_path = None
        self.is_processing = False

        # Khởi tạo Node & CLI
        self.node_path = find_node_executable()
        self.gwr_cli_path = find_gwr_cli()
        self.msg_queue = queue.Queue()

        self._setup_styles()
        self._build_ui()
        self._check_environment()
        self._poll_msg_queue()

    def _poll_msg_queue(self):
        try:
            while not self.msg_queue.empty():
                msg_type, *args = self.msg_queue.get_nowait()
                if msg_type == "success":
                    cleaned_pil, output_temp_path, meta_json = args
                    self._on_removal_success(cleaned_pil, output_temp_path, meta_json)
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
            text="📂  Chọn Ảnh...",
            font=("Segoe UI", 9, "bold"),
            bg=COLOR_PRIMARY,
            fg=COLOR_TEXT_WHITE,
            activebackground=COLOR_PRIMARY_HOVER,
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.select_input_file
        )
        self.btn_open.pack(side=tk.LEFT, padx=5)

        self.btn_process = tk.Button(
            action_bar,
            text="⚡  Xóa Watermark",
            font=("Segoe UI", 9, "bold"),
            bg="#2563eb",
            fg=COLOR_TEXT_WHITE,
            activebackground="#1d4ed8",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.start_watermark_removal
        )
        self.btn_process.pack(side=tk.LEFT, padx=5)

        self.btn_save = tk.Button(
            action_bar,
            text="💾  Lưu Ảnh...",
            font=("Segoe UI", 9),
            bg=COLOR_CARD_BORDER,
            fg=COLOR_TEXT_WHITE,
            activebackground="#374151",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.save_output_file
        )
        self.btn_save.pack(side=tk.LEFT, padx=5)

        self.btn_copy = tk.Button(
            action_bar,
            text="📋  Copy Ảnh",
            font=("Segoe UI", 9),
            bg=COLOR_CARD_BORDER,
            fg=COLOR_TEXT_WHITE,
            activebackground="#374151",
            activeforeground=COLOR_TEXT_WHITE,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.copy_to_clipboard
        )
        self.btn_copy.pack(side=tk.LEFT, padx=5)

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

        tk.Label(left_header, text="ẢNH GỐC (ORIGINAL)", font=("Segoe UI", 9, "bold"), bg=COLOR_PANEL, fg=COLOR_TEXT_MUTED).pack(side=tk.LEFT, pady=8)
        self.lbl_orig_info = tk.Label(left_header, text="Chưa có ảnh", font=("Consolas", 8), bg=COLOR_PANEL, fg=COLOR_TEXT_DIM)
        self.lbl_orig_info.pack(side=tk.RIGHT, pady=8)

        self.canvas_orig = tk.Canvas(left_card, bg="#0d0e15", highlightthickness=0)
        self.canvas_orig.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.canvas_orig.bind("<Configure>", lambda e: self._redraw_original())

        # Card Phải: Ảnh Đã Xóa Watermark
        right_card = tk.Frame(content_frame, bg=COLOR_CARD, highlightbackground=COLOR_CARD_BORDER, highlightthickness=1)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        right_header = tk.Frame(right_card, bg=COLOR_PANEL, height=36, padx=12)
        right_header.pack(fill=tk.X, side=tk.TOP)
        right_header.pack_propagate(False)

        tk.Label(right_header, text="KẾT QUẢ (REVERSE ALPHA BLENDING)", font=("Segoe UI", 9, "bold"), bg=COLOR_PANEL, fg=COLOR_PRIMARY).pack(side=tk.LEFT, pady=8)
        self.lbl_clean_info = tk.Label(right_header, text="Đang chờ...", font=("Consolas", 8), bg=COLOR_PANEL, fg=COLOR_TEXT_DIM)
        self.lbl_clean_info.pack(side=tk.RIGHT, pady=8)

        self.canvas_clean = tk.Canvas(right_card, bg="#0d0e15", highlightthickness=0)
        self.canvas_clean.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.canvas_clean.bind("<Configure>", lambda e: self._redraw_cleaned())

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
            text="Chọn một ảnh do Gemini AI tạo để bắt đầu nhận diện và loại bỏ watermark.",
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

    def select_input_file(self):
        if self.is_processing:
            return
        
        file_path = filedialog.askopenfilename(
            title="Chọn ảnh cần xóa watermark",
            filetypes=[
                ("Tất cả định dạng hỗ trợ", "*.png;*.jpg;*.jpeg;*.webp"),
                ("PNG Image", "*.png"),
                ("JPEG Image", "*.jpg;*.jpeg"),
                ("WebP Image", "*.webp"),
                ("Mọi tệp", "*.*")
            ]
        )
        if not file_path:
            return

        self.load_input_file(file_path)

    def load_input_file(self, file_path):
        try:
            img = Image.open(file_path)
            self.original_image = img
            self.input_file_path = file_path
            self.cleaned_image = None
            self.processed_temp_path = None

            w, h = img.size
            self.lbl_orig_info.config(text=f"{Path(file_path).name} ({w}×{h})")
            self.lbl_clean_info.config(text="Đang chờ xử lý...")
            self.btn_process.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.DISABLED)
            self.btn_copy.config(state=tk.DISABLED)

            self._redraw_original()
            self._clear_cleaned()
            self._clear_roi()

            self.lbl_status.config(text=f"Đã mở ảnh: {Path(file_path).name}", fg=COLOR_TEXT_WHITE)

            # Tự động thực hiện xóa watermark ngay khi mở ảnh
            self.start_watermark_removal()
        except Exception as err:
            messagebox.showerror("Lỗi mở ảnh", f"Không thể đọc tệp ảnh:\n{str(err)}")

    def start_watermark_removal(self):
        if not self.original_image or self.is_processing:
            return
        if not self.node_path or not self.gwr_cli_path:
            messagebox.showerror("Thiếu môi trường", "Chưa sẵn sàng Node.js hoặc CLI engine để xử lý.")
            return

        self.is_processing = True
        self.btn_open.config(state=tk.DISABLED)
        self.btn_process.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_copy.config(state=tk.DISABLED)

        self.progressbar.pack(side=tk.RIGHT, pady=9)
        self.progressbar.start(10)
        self.lbl_status.config(text="⏳ Đang phân tích thuật toán Reverse Alpha Blending...", fg=COLOR_ACCENT)

        thread = threading.Thread(target=self._run_removal_worker, daemon=True)
        thread.start()

    def _run_removal_worker(self):
        temp_dir = tempfile.mkdtemp(prefix="gwr_gui_")
        output_temp_path = os.path.join(temp_dir, "cleaned_output.png")

        cmd = [
            self.node_path,
            self.gwr_cli_path,
            "remove",
            self.input_file_path,
            "--output",
            output_temp_path,
            "--overwrite",
            "--json"
        ]

        try:
            # Chọn cwd là thư mục gốc của repo chứa node_modules
            cwd_path = str(Path(self.gwr_cli_path).resolve().parent.parent) if self.gwr_cli_path else str(get_base_dir())
            process = subprocess.run(
                cmd,
                cwd=cwd_path,
                capture_output=True,
                text=True,
                timeout=60
            )

            if process.returncode != 0:
                err_msg = process.stderr.strip() or process.stdout.strip() or f"Mã thoát: {process.returncode}"
                self.msg_queue.put(("error", err_msg))
                return

            # Đọc JSON đầu ra
            stdout_clean = process.stdout.strip()
            meta_json = None
            if stdout_clean:
                try:
                    # Tìm chuỗi JSON trong trường hợp có warning kèm theo
                    lines = stdout_clean.splitlines()
                    for line in reversed(lines):
                        line = line.strip()
                        if line.startswith("{") and line.endswith("}"):
                            meta_json = json.loads(line)
                            break
                except Exception:
                    pass

            # Kiểm tra tệp kết quả
            if not os.path.exists(output_temp_path):
                self.msg_queue.put(("error", "Lệnh chạy xong nhưng không tạo ra tệp ảnh kết quả."))
                return

            cleaned_pil = Image.open(output_temp_path)
            self.msg_queue.put(("success", cleaned_pil, output_temp_path, meta_json))

        except subprocess.TimeoutExpired:
            self.msg_queue.put(("error", "Hết thời gian chờ (quá 60 giây)."))
        except Exception as e:
            self.msg_queue.put(("error", str(e)))

    def _on_removal_success(self, cleaned_pil, output_temp_path, meta_json):
        self.is_processing = False
        self.progressbar.stop()
        self.progressbar.pack_forget()

        self.btn_open.config(state=tk.NORMAL)
        self.btn_process.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.NORMAL)
        self.btn_copy.config(state=tk.NORMAL)

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

    def _on_removal_error(self, err_msg):
        self.is_processing = False
        self.progressbar.stop()
        self.progressbar.pack_forget()

        self.btn_open.config(state=tk.NORMAL)
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
            text="Chọn một ảnh do Gemini AI tạo để bắt đầu nhận diện và loại bỏ watermark.",
            fg=COLOR_TEXT_MUTED
        )

    def _clear_cleaned(self):
        self.canvas_clean.delete("all")
        self.lbl_clean_info.config(text="Đang chờ...", fg=COLOR_TEXT_DIM)

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

    def _redraw_original(self):
        if self.original_image:
            self._tk_orig = self._fit_image_to_canvas(self.original_image, self.canvas_orig)

    def _redraw_cleaned(self):
        if self.cleaned_image:
            self._tk_clean = self._fit_image_to_canvas(self.cleaned_image, self.canvas_clean)

    def save_output_file(self):
        if not self.cleaned_image or not self.input_file_path:
            return

        orig_path = Path(self.input_file_path)
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

            self.lbl_status.config(text="📋 Đã sao chép ảnh vào Clipboard! Bạn có thể dán (Ctrl+V) ngay.", fg=COLOR_SUCCESS)
        except Exception as e:
            messagebox.showerror("Lỗi Clipboard", f"Không thể copy ảnh vào clipboard:\n{str(e)}")

def main():
    app = WatermarkRemoverApp()
    app.mainloop()

if __name__ == "__main__":
    main()
