"""Make the competition's own modules importable when pytest runs from the repo root.

In the sandbox the images copy env/ to /app/env/ and run with /app on sys.path, so
`import env` and `import referee` resolve for free. Locally we reproduce that layout.
"""

import sys
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR), str(COMP_DIR / "referee")]
