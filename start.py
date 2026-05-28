#!/usr/bin/env python3
"""
Cross-platform startup script for teaching-assistant project.
Starts both backend (FastAPI/Uvicorn) and frontend (Vite) services.

Usage:
    python start.py

Environment variables:
    PYTHON_PATH - Custom Python executable path
    BACKEND_PORT - Backend port (default: 8000)
    FRONTEND_PORT - Frontend port (default: 5173)
"""

import os
import sys
import subprocess
import signal
import platform
import time
import threading
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Load key=value pairs from .env file into os.environ (only if key not already set)."""
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


# Configuration
ROOT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

_load_env_file(ROOT_DIR / ".env")

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))

# Colors
class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    DIM = "\033[90m"
    END = "\033[0m"

if platform.system() == "Windows":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def log(prefix: str, color: str, message: str) -> None:
    print(f"{color}[{prefix:>8}]{Colors.END} {message}", flush=True)


def find_python() -> str:
    if env_path := os.environ.get("PYTHON_PATH"):
        return env_path

    conda_path = Path(r"C:\ProgramData\miniconda3\envs\learn\python.exe")
    if conda_path.exists():
        return str(conda_path)

    return sys.executable


PYTHON_EXE = find_python()
processes: list[tuple[str, subprocess.Popen, str]] = []


def start_backend() -> subprocess.Popen:
    log("BACKEND", Colors.BLUE, f"Starting FastAPI on port {BACKEND_PORT}")
    log("BACKEND", Colors.DIM, f"Using Python: {PYTHON_EXE}")

    cmd = [
        PYTHON_EXE, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(BACKEND_PORT),
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)

    proc = subprocess.Popen(
        cmd,
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    processes.append(("BACKEND", proc, Colors.BLUE))
    return proc


def start_frontend() -> subprocess.Popen:
    log("FRONTEND", Colors.GREEN, "Starting Vite dev server")

    proc = subprocess.Popen(
        ["npm.cmd", "run", "dev"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    processes.append(("FRONTEND", proc, Colors.GREEN))
    return proc


def stream_output(name: str, proc: subprocess.Popen, color: str) -> None:
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(name, color, line)
    except Exception as e:
        log(name, Colors.RED, f"Output stream error: {e}")


def shutdown(signum=None, frame=None) -> None:
    log("SYSTEM", Colors.YELLOW, "Shutting down services...")

    for name, proc, _ in processes:
        if proc.poll() is None:
            log("SYSTEM", Colors.DIM, f"Stopping {name} (PID {proc.pid})")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log("SYSTEM", Colors.RED, f"Force killing {name}")
                proc.kill()
            except Exception as e:
                log(name, Colors.RED, f"Error stopping {name}: {e}")

    log("SYSTEM", Colors.GREEN, "All services stopped")
    sys.exit(0)


def main() -> None:
    print(f"{Colors.CYAN}{'=' * 60}{Colors.END}")
    print(f"{Colors.CYAN}  中学伴学助教 - 开发环境启动器{Colors.END}")
    print(f"{Colors.CYAN}{'=' * 60}{Colors.END}")
    print()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    if not BACKEND_DIR.exists():
        log("ERROR", Colors.RED, f"Backend directory not found: {BACKEND_DIR}")
        sys.exit(1)
    if not FRONTEND_DIR.exists():
        log("ERROR", Colors.RED, f"Frontend directory not found: {FRONTEND_DIR}")
        sys.exit(1)

    start_backend()
    time.sleep(1.5)
    start_frontend()

    print()
    log("SYSTEM", Colors.CYAN, f"Backend:  http://localhost:{BACKEND_PORT}")
    log("SYSTEM", Colors.CYAN, f"Frontend: http://localhost:{FRONTEND_PORT}")
    log("SYSTEM", Colors.YELLOW, "Press Ctrl+C to stop all services")
    print()

    for name, proc, color in processes:
        t = threading.Thread(
            target=stream_output, args=(name, proc, color), daemon=True
        )
        t.start()

    try:
        for name, proc, color in processes:
            proc.wait()
            log(name, color, "Process exited")
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
