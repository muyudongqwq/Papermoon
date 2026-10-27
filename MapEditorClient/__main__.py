import argparse
from pathlib import Path

from MapEditorClient.app import main


def run():
    parser = argparse.ArgumentParser(description="Papermoon Map Editor")
    parser.add_argument("map", nargs="?", type=Path)
    args = parser.parse_args()
    return main(args.map)


if __name__ == "__main__":
    raise SystemExit(run())

