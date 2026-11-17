"""Start Mouser. Double-click this file (runs without a console via pythonw),
or run `python run.pyw` to see log output."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mouser.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
