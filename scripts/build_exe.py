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

    # 3. Chuẩn bị file icon Windows (.ico)
    icon_png = ROOT_DIR / "src" / "extension" / "assets" / "icon-128.png"
    icon_ico = ROOT_DIR / "src" / "extension" / "assets" / "app-icon.ico"
    if icon_png.is_file():
        try:
            from PIL import Image
            img = Image.open(icon_png)
            sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
            img.save(icon_ico, format='ICO', sizes=sizes)
            print(f"✔ Đã tạo file icon Windows: {icon_ico}")
        except Exception as e:
            print(f"⚠ Lỗi tạo icon: {e}")

    # 4. Tìm node.exe để đóng gói kèm (đảm bảo hoàn toàn độc lập, không cần cài Node.js trên máy)
    node_exe = shutil.which("node")
    if not node_exe:
        default_paths = [
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "nodejs" / "node.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "nodejs" / "node.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "node" / "node.exe",
        ]
        for p in default_paths:
            if p.is_file():
                node_exe = str(p)
                break

    # 5. Chạy PyInstaller
    print("\n[Bước 2/3] Đóng gói GUI bằng PyInstaller...")

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
    ]

    if icon_ico.is_file():
        pyinstaller_cmd.extend(["--icon", str(icon_ico)])

    if node_exe and os.path.isfile(node_exe):
        print(f"✔ Đóng gói kèm Node.js runtime ({node_exe})")
        pyinstaller_cmd.extend(["--add-binary", f"{node_exe}{os.pathsep}."])

    # Đính kèm cli bundle và các tài nguyên cần thiết
    pyinstaller_cmd.extend([
        "--add-data", f"{ROOT_DIR / 'dist' / 'cli-bundle.mjs'}{os.pathsep}dist",
        "--add-data", f"{ROOT_DIR / 'bin'}{os.pathsep}bin",
        "--add-data", f"{ROOT_DIR / 'src'}{os.pathsep}src",
    ])
    if icon_ico.is_file():
        pyinstaller_cmd.extend(["--add-data", f"{icon_ico}{os.pathsep}assets"])
    if icon_png.is_file():
        pyinstaller_cmd.extend(["--add-data", f"{icon_png}{os.pathsep}assets"])

    pyinstaller_cmd.append(str(ROOT_DIR / "gui_app.py"))

    run_cmd(pyinstaller_cmd)

    exe_output = release_dir / "GeminiWatermarkRemover.exe"
    if exe_output.is_file():
        size_mb = exe_output.stat().st_size / (1024 * 1024)
        print("\n==================================================")
        print(f"🎉 THÀNH CÔNG! Đã tạo file EXE độc lập:")
        print(f"   Đường dẫn: {exe_output}")
        print(f"   Dung lượng: {size_mb:.2f} MB")
        print("==================================================")

        # 6. Tự động tạo Shortcut trên Màn hình chính (Desktop)
        try:
            desktop_dir = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
            if desktop_dir.is_dir():
                shortcut_path = desktop_dir / "Gemini Watermark Remover.lnk"
                vbs_script = f'''Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{exe_output}"
oLink.WorkingDirectory = "{release_dir}"
oLink.Description = "Gemini AI Watermark Remover Tool"
oLink.IconLocation = "{exe_output},0"
oLink.Save
'''
                vbs_path = ROOT_DIR / "build" / "create_shortcut.vbs"
                vbs_path.parent.mkdir(parents=True, exist_ok=True)
                vbs_path.write_text(vbs_script, encoding="utf-8")
                subprocess.run(["cscript", "//nologo", str(vbs_path)], check=False)
                if shortcut_path.is_file():
                    print(f"✔ Đã tạo lối tắt trên Desktop: {shortcut_path}")
                    print("👉 Bạn có thể bấm chuột phải vào icon này và chọn 'Pin to taskbar' (Ghim vào thanh tác vụ)!")
        except Exception as e:
            print(f"⚠ Không thể tạo shortcut desktop: {e}")
    else:
        print("❌ Không tìm thấy file EXE sau khi đóng gói.")
        sys.exit(1)

if __name__ == "__main__":
    main()
