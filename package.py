"""
package.py — VRCTTP 打包脚本

用法：
    python package.py

流程：
    1. 使用 PyInstaller + main.spec 构建程序
    2. 将 config.json 复制为 dist/main/tmp/example_config.json
    3. 在 dist/main/ 内创建空的 models 文件夹（用于放置本地语音识别模型）
    4. 将主程序 dist/main/main.exe 重命名为 VRCTTP v{VERSION}.exe
    5. 将输出文件夹 dist/main 重命名为 dist/VRCTTP
"""

import os
import shutil
import subprocess
import sys

# ── 版本号 ────────────────────────────────────────────────────────────────
VERSION = "0.3.0"

# ── 路径常量 ──────────────────────────────────────────────────────────────
ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE     = os.path.join(ROOT_DIR, "main.spec")
CONFIG_SRC    = os.path.join(ROOT_DIR, "config.json")
DIST_MAIN     = os.path.join(ROOT_DIR, "dist", "main")
MODELS_DIR    = os.path.join(DIST_MAIN, "models")
SRC_EXE       = os.path.join(DIST_MAIN, "main.exe")
DST_EXE       = os.path.join(DIST_MAIN, f"VRCTTP v{VERSION}.exe")
DIST_VRCTTP   = os.path.join(ROOT_DIR, "dist", "VRCTTP")


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
    step(f"重命名 exe → VRCTTP v{VERSION}.exe")
    if not os.path.isfile(SRC_EXE):
        sys.exit(f"❌ 找不到 {SRC_EXE}")
    if os.path.isfile(DST_EXE):
        os.remove(DST_EXE)
    os.rename(SRC_EXE, DST_EXE)
    print(f"✅ {os.path.basename(SRC_EXE)}  →  {os.path.basename(DST_EXE)}")


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
    copy_config()
    create_models_dir()
    rename_exe()
    rename_dist_folder()

    step("打包完成")
    print(f"  输出目录 : dist/VRCTTP/")
    print(f"  主程序   : dist/VRCTTP/VRCTTP v{VERSION}.exe")
    print(f"  模型目录 : dist/VRCTTP/models/  (请手动放置模型文件)")
