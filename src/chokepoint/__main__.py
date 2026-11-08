"""Entry point for `python -m chokepoint`.

The console script is added in Phase 9; this makes the CLI usable now.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
