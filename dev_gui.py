"""GUI开发模式 — 文件变更自动重启。"""

import subprocess
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIRS = ["gui/", "resources/"]
WATCH_EXTENSIONS = {".py", ".qss", ".svg", ".yaml"}

class ReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self._need_restart = False

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix in WATCH_EXTENSIONS:
            print(f"[RELOAD] {path.name} changed")
            self._need_restart = True

    def should_restart(self) -> bool:
        if self._need_restart:
            self._need_restart = False
            return True
        return False


def run_gui():
    return subprocess.Popen(
        [sys.executable, "app.py", "--mode", "slave", "--port", "2409"],
        cwd=str(Path(__file__).parent)
    )


def main():
    print("=" * 50)
    print("  IEC 104 GUI 开发模式")
    print("  修改 gui/ 或 resources/ 下的文件将自动重启")
    print("  按 Ctrl+C 退出")
    print("=" * 50)

    handler = ReloadHandler()
    observer = Observer()
    for d in WATCH_DIRS:
        path = Path(__file__).parent / d
        if path.exists():
            observer.schedule(handler, str(path), recursive=True)
            print(f"  监控: {d}")
    observer.start()

    proc = run_gui()

    try:
        while True:
            time.sleep(0.5)
            if handler.should_restart():
                print("[RELOAD] Restarting GUI...")
                proc.terminate()
                proc.wait(timeout=5)
                proc = run_gui()
    except KeyboardInterrupt:
        print("\n[EXIT] Stopping...")
        proc.terminate()
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
