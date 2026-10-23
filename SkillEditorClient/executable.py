"""Build target; normal source launches use python -m SkillEditorClient."""

from SkillEditorClient.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
