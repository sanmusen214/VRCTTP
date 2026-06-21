"""
package.py — VRCTTP 打包脚本

用法：
    python package.py

流程：
    1. 使用 PyInstaller + main.spec 构建程序
    2. 净化 .env（将所有值替换为键名，防止密钥泄露），复制到 dist/main/_internal/
    3. 将 config.json 复制到打包目录根（dist/main/）
    4. 在 dist/main/ 内创建空的 models 文件夹（用于放置本地语音识别模型）
    5. 将主程序 dist/main/main.exe 重命名为 VRCTTP v{VERSION}.exe
    6. 将输出文件夹 dist/main 重命名为 dist/VRCTTP
"""

import os
import re
import shutil
import subprocess
import sys

# ── 版本号 ────────────────────────────────────────────────────────────────
VERSION = "0.1.2"

# ── 路径常量 ──────────────────────────────────────────────────────────────
ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE     = os.path.join(ROOT_DIR, "main.spec")
ENV_SRC       = os.path.join(ROOT_DIR, ".env")
CONFIG_SRC    = os.path.join(ROOT_DIR, "config.json")
DIST_MAIN     = os.path.join(ROOT_DIR, "dist", "main")
INTERNAL_DIR  = os.path.join(DIST_MAIN, "_internal")
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


# ── Step 2: 净化 .env 并复制 ─────────────────────────────────────────────

def _sanitize_env(src_path: str) -> str:
    """
    读取 .env 文件，将所有赋值行的值替换为键名（防止密钥泄露）。
    注释行和空行原样保留。
    返回处理后的内容字符串。
    """
    lines_out = []
    with open(src_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip("\n")
            # 赋值行：KEY=VALUE（允许 KEY 为空值）
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)', stripped)
            if m:
                key = m.group(1)
                lines_out.append(f"{key}={key}\n")
            else:
                lines_out.append(line if line.endswith("\n") else line + "\n")
    return "".join(lines_out)


def copy_env() -> None:
    step("净化 .env 并复制到 _internal/")
    if not os.path.isfile(ENV_SRC):
        print("⚠  未找到 .env 文件，跳过")
        return
    os.makedirs(INTERNAL_DIR, exist_ok=True)
    sanitized = _sanitize_env(ENV_SRC)
    dst = os.path.join(INTERNAL_DIR, ".env")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(sanitized)
    print(f"✅ 净化后的 .env 已写入: {dst}")


# ── Step 3: 复制 config.json ─────────────────────────────────────────────

def copy_config() -> None:
    step("复制 config.json 到打包目录")
    if not os.path.isfile(CONFIG_SRC):
        print("⚠  未找到 config.json，跳过")
        return
    dst = os.path.join(DIST_MAIN, "config.json")
    shutil.copy2(CONFIG_SRC, dst)
    print(f"✅ config.json 已复制到: {dst}")


# ── Step 4: 创建空 models 文件夹 ──────────────────────────────────────────

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
    copy_env()
    copy_config()
    create_models_dir()
    rename_exe()
    rename_dist_folder()

    step("打包完成")
    print(f"  输出目录 : dist/VRCTTP/")
    print(f"  主程序   : dist/VRCTTP/VRCTTP v{VERSION}.exe")
    print(f"  模型目录 : dist/VRCTTP/models/  (请手动放置模型文件)")
