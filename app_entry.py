"""Entry script for PyInstaller. Wraps biofeedback.main as a runnable file.

When running inside a PyInstaller bundle (`sys.frozen`), the Qt platform
plugin path is not automatically set, so we locate the bundled plugins and
export QT_QPA_PLATFORM_PLUGIN_PATH before importing any Qt code.
"""
import os
import sys


def _setup_qt_plugin_path() -> None:
    if not getattr(sys, "frozen", False):
        return
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "PyQt6", "Qt6", "plugins"))
    exe_dir = os.path.dirname(sys.executable)
    candidates.append(os.path.join(exe_dir, "..", "Frameworks", "PyQt6", "Qt6", "plugins"))
    candidates.append(os.path.join(exe_dir, "..", "Resources", "PyQt6", "Qt6", "plugins"))
    for path in candidates:
        full = os.path.abspath(path)
        if os.path.isdir(os.path.join(full, "platforms")):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = full
            return


_setup_qt_plugin_path()

from biofeedback.main import main


if __name__ == "__main__":
    main()
