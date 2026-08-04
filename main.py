import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import tkinter as tk
from gui import ZapretFuzzerApp


def main():
    root = tk.Tk()
    app = ZapretFuzzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()