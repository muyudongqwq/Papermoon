import argparse
from pathlib import Path

from core.catalog import DEFAULT_CATALOG
from skilleditor.app import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Papermoon本地技能编辑器")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    raise SystemExit(main(args.catalog))
