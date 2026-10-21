"""Validated JSON overrides shared by the core and the desktop skill editor."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from game.character.card_data import CHARACTER_CARD_DATA
from game.character.card_factory import validate_character_card_catalog
from game.skill.content_registry import CONTENT_CATALOGS, validate_content_catalogs
from game.skill.class_skill_data import CLASS_SKILL_DATA
from game.rank.rank import SkillRank

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "userdata" / "catalog.json"
CATEGORIES = ("personal_skill", "class_skill", "basic_magic", "noble_phantasm", "character_card")
LIVE_CATALOGS = {**CONTENT_CATALOGS, "character_card": CHARACTER_CARD_DATA}
BUILTINS = deepcopy(LIVE_CATALOGS)
BUILTINS["class_skill"] = {name: {"name": name, "ranks": deepcopy(ranks)}
                           for name, ranks in CLASS_SKILL_DATA.items()}
_CATALOG_LOCK = RLock()


def empty_project():
    return {"format_version": 1, **{category: {} for category in CATEGORIES}}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON存在重复字段：{key}")
        result[key] = value
    return result


def parse_json(text):
    def invalid_constant(value):
        raise ValueError(f"JSON不允许非有限数值：{value}")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=invalid_constant)


@contextmanager
def _installed(catalogs):
    # Mutate existing dictionaries so all legacy import references agree.
    # A scope must span the complete synchronous game, never a running Session
    # in a different thread. The editor launches testing in a separate process.
    with _CATALOG_LOCK:
        previous = {key: dict(value) for key, value in LIVE_CATALOGS.items()}
        previous_classes = dict(CLASS_SKILL_DATA)
        try:
            for key, value in LIVE_CATALOGS.items():
                value.clear()
                value.update(deepcopy(catalogs[key]))
            CLASS_SKILL_DATA.clear()
            CLASS_SKILL_DATA.update({name: deepcopy(definition["ranks"])
                                     for name, definition in catalogs["class_skill"].items()})
            yield
        finally:
            for key, value in LIVE_CATALOGS.items():
                value.clear()
                value.update(previous[key])
            CLASS_SKILL_DATA.clear()
            CLASS_SKILL_DATA.update(previous_classes)


class CatalogProject:
    def __init__(self, path=DEFAULT_CATALOG):
        self.path = Path(path).resolve()
        self._saved_bytes = self.path.read_bytes() if self.path.exists() else None
        self.data = empty_project() if self._saved_bytes is None else parse_json(self._saved_bytes.decode("utf-8-sig"))
        # Version 1 originally contained four directories. Upgrade in memory
        # only; the user's file and backup stay untouched until an explicit save.
        if isinstance(self.data, dict) and set(self.data) == {"format_version", *(set(CATEGORIES) - {"class_skill"})}:
            self.data["class_skill"] = {}
        self.validate()

    def effective(self):
        return {category: {**deepcopy(BUILTINS[category]), **deepcopy(self.data[category])}
                for category in CATEGORIES}

    def validate(self):
        data = self.data
        if not isinstance(data, dict) or set(data) != {"format_version", *CATEGORIES}:
            raise ValueError("项目必须包含format_version及五个内容目录")
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("不支持的项目格式版本")
        for category in CATEGORIES:
            if not isinstance(data[category], dict):
                raise ValueError(f"{category}必须是目录对象")
            for key, definition in data[category].items():
                if not isinstance(key, str) or not key.strip() or not isinstance(definition, dict):
                    raise ValueError(f"{category}条目必须有非空ID和对象定义")
                if category == "class_skill":
                    if set(definition) != {"name", "ranks"} or definition["name"] != key:
                        raise ValueError("职介技能必须包含与目录名称一致的name，以及ranks等级定义")
                    ranks = definition["ranks"]
                    if not isinstance(ranks, dict) or not ranks:
                        raise ValueError("职介技能ranks必须是非空等级对象")
                    for rank, components in ranks.items():
                        SkillRank(rank)
                        if not isinstance(components, list):
                            raise ValueError("职介技能每个等级必须对应组件列表")
                    if not any(ranks.values()):
                        raise ValueError("职介技能必须至少定义一个非空等级")
                    continue
                expected = key if category != "basic_magic" else f"basic_magic:{key}"
                field = "card_id" if category == "character_card" else "skill_id"
                if definition.get(field) != expected:
                    raise ValueError(f"目录ID {key} 与 {field} 不一致，应为 {expected}")
        # Reject NaN and Python objects even for callers bypassing JSON input.
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        with _installed(self.effective()):
            result = validate_content_catalogs()
            result["character_card"] = validate_character_card_catalog()
        return {key: len(value) for key, value in result.items()}

    def put(self, category, key, definition):
        if category not in CATEGORIES:
            raise ValueError(f"未知目录：{category}")
        previous = deepcopy(self.data)
        try:
            self.data[category][key] = deepcopy(definition)
            self.validate()
        except Exception:
            self.data = previous
            raise

    def remove_override(self, category, key):
        previous = deepcopy(self.data)
        try:
            self.data[category].pop(key, None)
            self.validate()
        except Exception:
            self.data = previous
            raise

    @contextmanager
    def activate(self):
        self.validate()
        with _installed(self.effective()):
            yield

    def save(self):
        self.validate()
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self._saved_bytes:
            raise ValueError("项目文件已被其他程序修改，请重新打开后再编辑，避免覆盖")
        payload = (json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if current is not None:
            self.path.with_suffix(self.path.suffix + ".bak").write_bytes(current)
        descriptor, temporary = tempfile.mkstemp(prefix=".catalog-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self._saved_bytes = payload
