#!/usr/bin/env python3
"""
Production startup script for teaching-assistant project.
Starts backend with multi-worker Uvicorn — frontend served as static files.

Usage:
    python start_prod.py           # foreground mode
    python start_prod.py --daemon  # background mode (Windows)
    pythonw start_prod.py          # no console window (Windows)

Environment variables:
    PYTHON_PATH    - Custom Python executable path
    BACKEND_PORT   - Backend port (default: 8000)
    WORKERS        - Uvicorn worker count (default: 1)
                     WARNING: keep at 1. BM25 检索缓存、课文名映射、入库文件锁均为
                     进程内状态，多 worker 会导致缓存失效丢失与并发写入损坏。
    LOG_DIR        - Log directory (default: ./logs)
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime


def _load_env_file(path: Path) -> None:
    """Load key=value pairs from .env file into os.environ."""
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                if key not in os.environ:
                    os.environ[key] = value


ROOT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
LOG_DIR = Path(os.environ.get("LOG_DIR", ROOT_DIR / "logs"))

_load_env_file(ROOT_DIR / ".env")

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
WORKERS = int(os.environ.get("WORKERS", "1"))


def find_python() -> str:
    if env_path := os.environ.get("PYTHON_PATH"):
        return env_path

    # Prefer the uv-managed virtual environment (created by `uv sync` in backend/)
    uv_venv = BACKEND_DIR / ".venv"
    for candidate in (uv_venv / "Scripts" / "python.exe", uv_venv / "bin" / "python"):
        if candidate.exists():
            return str(candidate)

    conda_path = Path(r"C:\ProgramData\miniconda3\envs\learn\python.exe")
    if conda_path.exists():
        return str(conda_path)
    return sys.executable


PYTHON_EXE = find_python()


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if LOG_DIR.exists():
        log_file = LOG_DIR / "app.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def build_frontend() -> bool:
    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if dist_index.exists():
        log("[BUILD] frontend/dist exists, skipping build")
        return True

    log("[BUILD] Building frontend static files...")
    result = subprocess.run(
        ["npm.cmd", "run", "build"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        log("[BUILD] Frontend build FAILED")
        print(result.stdout, file=sys.stderr)
        return False

    log("[BUILD] Frontend build succeeded")
    return True


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Production server starter")
    parser.add_argument("--daemon", action="store_true", help="Run in background (detached)")
    args = parser.parse_args()

    ensure_log_dir()

    log("=" * 50)
    log("Production server starting...")
    log(f"Port: {BACKEND_PORT}, Workers: {WORKERS}")

    if WORKERS > 1:
        log("[WARN] WORKERS > 1：BM25 缓存失效、课文名映射、入库文件锁均为进程内状态，")
        log("[WARN] 多 worker 会导致检索结果陈旧与 ingest_index.json 并发写损坏，请保持 WORKERS=1！")

    if not BACKEND_DIR.exists():
        log(f"[ERROR] Backend directory not found: {BACKEND_DIR}")
        sys.exit(1)
    if not FRONTEND_DIR.exists():
        log(f"[ERROR] Frontend directory not found: {FRONTEND_DIR}")
        sys.exit(1)

    if not build_frontend():
        sys.exit(1)

    cmd = [
        PYTHON_EXE, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(BACKEND_PORT),
        "--workers", str(WORKERS),
        "--log-level", "info",
        "--access-log",
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)

    out_file = LOG_DIR / "app.log"

    if args.daemon:
        log("[SYSTEM] Starting in background mode...")
        with open(out_file, "a", encoding="utf-8") as out:
            proc = subprocess.Popen(
                cmd,
                cwd=BACKEND_DIR,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE,
            )
        log(f"[SYSTEM] Server PID: {proc.pid}")
        log(f"[SYSTEM] Log file: {out_file}")
        log(f"[SYSTEM] URL: http://0.0.0.0:{BACKEND_PORT}")
        return

    log("[SYSTEM] Starting in foreground mode...")
    log(f"[SYSTEM] URL: http://0.0.0.0:{BACKEND_PORT}")
    log("[SYSTEM] Press Ctrl+C to stop")
    log("-" * 50)

    try:
        with open(out_file, "a", encoding="utf-8") as out:
            proc = subprocess.Popen(
                cmd,
                cwd=BACKEND_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log(line)
                    out.write(line + "\n")
                    out.flush()
    except KeyboardInterrupt:
        log("[SYSTEM] Received interrupt, shutting down...")
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        log("[SYSTEM] Server stopped")
    except Exception as e:
        log(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
