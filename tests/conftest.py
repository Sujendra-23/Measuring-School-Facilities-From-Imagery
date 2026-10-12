"""Make src/ importable the same way the pipeline scripts do (flat `import config`)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
