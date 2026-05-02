from __future__ import annotations

import sys

from astro_daily.cli import main as cli_main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    raise SystemExit(cli_main(argv))
