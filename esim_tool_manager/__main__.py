"""esim_tool_manager.__main__
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Package entry-point supporting `python -m esim_tool_manager`.
"""

import sys
from esim_tool_manager.cli import main

if __name__ == "__main__":
    sys.exit(main())
