#!/usr/bin/env python3
"""
Script đóng gói Gemini Watermark Remover GUI thành tệp EXE độc lập bằng PyInstaller.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Đảm bảo in UTF-8 không lỗi trên console Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent

def run_cmd(cmd, cwd=None):
    print(f"➜ Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd or str(ROOT_DIR))
    if res.returncode != 0:
        print(f"❌ Error running command (code {res.returncode})")
        sys.exit(res.returncode)

def main():
    print("==================================================")
    print("  ĐÓNG GÓI GEMINI WATERMARK REMOVER GUI (.EXE)")
    print("==================================================")

    # 1. Đảm bảo dist/cli-bundle.mjs được tạo
    print("\n[Bước 1/3] Biên dịch CLI bundle bằng esbuild...")
    node_build_script = """
import * as esbuild from 'esbuild';
await esbuild.build({
  entryPoints: ['bin/gwr.mjs'],
  bundle: true,
  platform: 'node',
  target: 'node20',
  outfile: 'dist/cli-bundle.mjs',
  format: 'esm',
  external: ['sharp', 'mediabunny', 'playwright', 'onnxruntime-web']
});
console.log('✔ CLI bundle built successfully at dist/cli-bundle.mjs');
"""
    run_cmd(["node", "-e", node_build_script])

    # 2. Chuẩn bị thư mục release
    release_dir = ROOT_DIR / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    # 3. Chạy PyInstaller
    print("\n[Bước 2/3] Đóng gói GUI bằng PyInstaller...")
    
    # Tìm icon nếu có
    icon_path = ROOT_DIR / "src" / "extension" / "assets" / "icon-128.png"
    icon_args = []
    # (Nếu có icon .ico thì thêm --icon)

    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", "GeminiWatermarkRemover",
        "--onefile",
        "--windowed",      # Không hiện console đen phía sau
        "--clean",
        "--distpath", str(release_dir),
        "--workpath", str(ROOT_DIR / "build" / "pyinstaller"),
        "--specpath", str(ROOT_DIR / "build" / "pyinstaller"),
        # Đính kèm cli bundle và các thư mục cần thiết
        "--add-data", f"{ROOT_DIR / 'dist' / 'cli-bundle.mjs'}{os.pathsep}dist",
        "--add-data", f"{ROOT_DIR / 'bin'}{os.pathsep}bin",
        "--add-data", f"{ROOT_DIR / 'src'}{os.pathsep}src",
        str(ROOT_DIR / "gui_app.py")
    ]

    run_cmd(pyinstaller_cmd)

    exe_output = release_dir / "GeminiWatermarkRemover.exe"
    if exe_output.is_file():
        size_mb = exe_output.stat().st_size / (1024 * 1024)
        print("\n==================================================")
        print(f"🎉 THÀNH CÔNG! Đã tạo file EXE:")
        print(f"   Đường dẫn: {exe_output}")
        print(f"   Dung lượng: {size_mb:.2f} MB")
        print("==================================================")
    else:
        print("❌ Không tìm thấy file EXE sau khi đóng gói.")
        sys.exit(1)

if __name__ == "__main__":
    main()
