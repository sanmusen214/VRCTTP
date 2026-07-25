"""
package.py — VRCTTP 打包脚本

用法：
    python package.py

流程：
    1. 使用 PyInstaller + main.spec 构建程序
    2. 使用 PyInstaller + update.spec 构建更新器
    3. 将 config.json 复制为 dist/main/tmp/example_config.json
    4. 在 dist/main/ 内创建空的 models 文件夹（用于放置本地语音识别模型）
    5. 将主程序重命名为 VRCTTP.exe，并放入 VRCTTP_UPDATE.exe
    6. 将更新器压缩为 VRCTTP{VERSION}_update.zip
    7. 将输出文件夹 dist/main 重命名为 dist/VRCTTP
"""

import os
import shutil
import subprocess
import sys
import zipfile
from version import version_str
# ── 版本号 ────────────────────────────────────────────────────────────────
VERSION = version_str

# ── 路径常量 ──────────────────────────────────────────────────────────────
ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE     = os.path.join(ROOT_DIR, "main.spec")
UPDATE_SPEC_FILE = os.path.join(ROOT_DIR, "update.spec")
CONFIG_SRC    = os.path.join(ROOT_DIR, "config.json")
DIST_MAIN     = os.path.join(ROOT_DIR, "dist", "main")
MODELS_DIR    = os.path.join(DIST_MAIN, "models")
SRC_EXE       = os.path.join(DIST_MAIN, "main.exe")
DST_EXE       = os.path.join(DIST_MAIN, "VRCTTP.exe")
SRC_UPDATE_EXE = os.path.join(ROOT_DIR, "dist", "update.exe")
DST_UPDATE_EXE = os.path.join(DIST_MAIN, "VRCTTP_UPDATE.exe")
UPDATE_ZIP     = os.path.join(DIST_MAIN, f"VRCTTP{VERSION}_update.zip")
DIST_VRCTTP   = os.path.join(ROOT_DIR, "dist", "VRCTTP")
UPDATE_DATA_DIRS = (
    os.path.join("_internal", "_tcl_data"),
    os.path.join("_internal", "_tk_data"),
)


def step(msg: str) -> None:
    print(f"\n{'─'*60}\n▶  {msg}\n{'─'*60}")


# ── Step 1: PyInstaller ───────────────────────────────────────────────────

def build() -> None:
    step(f"PyInstaller 打包  (版本 {VERSION})")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", SPEC_FILE],
        cwd=ROOT_DIR,
    )
    if result.returncode != 0:
        sys.exit(f"❌ PyInstaller 打包失败，退出码 {result.returncode}")
    print("✅ 打包完成")


def build_updater() -> None:
    step("PyInstaller 打包更新器")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", UPDATE_SPEC_FILE],
        cwd=ROOT_DIR,
    )
    if result.returncode != 0:
        sys.exit(f"❌ 更新器打包失败，退出码 {result.returncode}")
    print("✅ 更新器打包完成")


# ── Step 2: 复制默认配置模板 ─────────────────────────────────────────────

def copy_config() -> None:
    step("复制 config.json 为首次启动模板")
    if not os.path.isfile(CONFIG_SRC):
        print("⚠  未找到 config.json，跳过")
        return
    tmp_dir = os.path.join(DIST_MAIN, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    dst = os.path.join(tmp_dir, "example_config.json")
    shutil.copy2(CONFIG_SRC, dst)
    print(f"✅ config.json 已复制到: {dst}")


# ── Step 3: 创建空 models 文件夹 ──────────────────────────────────────────

def create_models_dir() -> None:
    step("创建空的 models 文件夹")
    os.makedirs(MODELS_DIR, exist_ok=True)
    # 放置一个 README，说明用途
    readme = os.path.join(MODELS_DIR, "README.txt")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(
                "将本地语音识别模型文件夹放置于此目录下。\n"
                "例如：models\\SenseVoiceSmall\\ 或 models\\paraformer\\\n"
                "模型目录应包含 model.pt / config.yaml 等模型文件。\n"
            )
    print(f"✅ models 文件夹已创建: {MODELS_DIR}")


# ── Step 4: 重命名 exe ────────────────────────────────────────────────────

def rename_exe() -> None:
    step("重命名主程序 exe → VRCTTP.exe")
    if not os.path.isfile(SRC_EXE):
        sys.exit(f"❌ 找不到 {SRC_EXE}")
    if os.path.isfile(DST_EXE):
        os.remove(DST_EXE)
    os.rename(SRC_EXE, DST_EXE)
    print(f"✅ {os.path.basename(SRC_EXE)}  →  {os.path.basename(DST_EXE)}")


def install_updater() -> None:
    step("安装更新器 → VRCTTP_UPDATE.exe")
    if not os.path.isfile(SRC_UPDATE_EXE):
        sys.exit(f"❌ 找不到更新器构建结果 {SRC_UPDATE_EXE}")
    if os.path.isfile(DST_UPDATE_EXE):
        os.remove(DST_UPDATE_EXE)
    shutil.move(SRC_UPDATE_EXE, DST_UPDATE_EXE)
    print(f"✅ 更新器已放入: {DST_UPDATE_EXE}")


def create_update_zip() -> None:
    step(f"压缩更新器 → {os.path.basename(UPDATE_ZIP)}")
    if not os.path.isfile(DST_UPDATE_EXE):
        sys.exit(f"❌ 找不到待压缩的更新器 {DST_UPDATE_EXE}")

    missing_dirs = [
        relative_dir
        for relative_dir in UPDATE_DATA_DIRS
        if not os.path.isdir(os.path.join(DIST_MAIN, relative_dir))
    ]
    if missing_dirs:
        sys.exit(f"❌ 找不到更新所需目录: {', '.join(missing_dirs)}")

    with zipfile.ZipFile(UPDATE_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(DST_UPDATE_EXE, arcname="VRCTTP_UPDATE.exe")
        archive.write(DST_EXE, arcname="VRCTTP.exe")
        for relative_dir in UPDATE_DATA_DIRS:
            source_dir = os.path.join(DIST_MAIN, relative_dir)
            for current_dir, _, filenames in os.walk(source_dir):
                for filename in filenames:
                    source_path = os.path.join(current_dir, filename)
                    archive_path = os.path.relpath(source_path, DIST_MAIN)
                    archive.write(source_path, arcname=archive_path)
    print(f"✅ 更新压缩包已创建: {UPDATE_ZIP}")


# ── Step 5: 重命名输出文件夹 ──────────────────────────────────────────────

def rename_dist_folder() -> None:
    step("重命名输出文件夹 dist/main → dist/VRCTTP")
    if os.path.isdir(DIST_VRCTTP):
        shutil.rmtree(DIST_VRCTTP)
    os.rename(DIST_MAIN, DIST_VRCTTP)
    print(f"✅ dist/main  →  dist/VRCTTP")


# ── 入口 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    build()
    build_updater()
    copy_config()
    create_models_dir()
    rename_exe()
    install_updater()
    create_update_zip()
    rename_dist_folder()

    step("打包完成")
    print(f"  输出目录 : dist/VRCTTP/")
    print("  主程序   : dist/VRCTTP/VRCTTP.exe")
    print("  更新器   : dist/VRCTTP/VRCTTP_UPDATE.exe")
    print(f"  更新包   : dist/VRCTTP/VRCTTP{VERSION}_update.zip")
    print(f"  模型目录 : dist/VRCTTP/models/  (请手动放置模型文件)")
