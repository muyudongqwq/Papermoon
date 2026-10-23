import argparse
from pathlib import Path

from core.catalog import DEFAULT_CATALOG
from SkillEditorClient.app import main


def run():
    parser = argparse.ArgumentParser(description="Papermoon SkillEditorClient 表单试验版")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    return main(args.catalog)


if __name__ == "__main__":
    raise SystemExit(run())
