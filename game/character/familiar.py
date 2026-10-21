"""Summoned familiar templates, runtime entities, and creation helpers."""

from copy import deepcopy

from .npc import NPC


DEFAULT_FAMILIAR_STAT_BLOCK = {
    "source": "fixed",
    "hp": 30,
    "mp": 0,
    "atk": 0,
    "attack_type": "physical",
    "attack_dice": 0,
    "defense_dice": 0,
    "movement": 1,
}

DEFAULT_FAMILIAR_ACTIONS = {
    "allow": ["move", "pass", "investigate", "dodge", "block"],
    "deny": [],
}

VALID_STAT_SOURCES = {"fixed", "summoner"}
VALID_ATTACK_TYPES = {"physical", "magic"}
VALID_DICE_OVERRIDES = {
    "physical_attack",
    "magic_attack",
    "dodge",
    "block",
    "offset",
    "perceive",
    "hide",
    "escape",
}


# This catalog intentionally contains only data.  More elaborate familiar
# abilities are loaded through the same skill component schema used by player
# characters instead of being hard-coded into Familiar.
FAMILIAR_TEMPLATE_DATA = {
    "basic_magic_familiar": {
        "template_id": "basic_magic_familiar",
        "name": "使魔",
        "stat_block": {
            "attributes": {
                "strength": 1,
                "endurance": 1,
                "flexibility": 1,
                "magic": 1,
                "fortune": 1,
            },
            "hp": 30,
            "mp": 0,
            "atk": 0,
            "attack_dice": 0,
            "defense_dice": 0,
            "movement": 1,
        },
        "actions": {
            "allow": ["move", "pass", "investigate", "dodge", "block"],
            "deny": ["attack", "offset"],
        },
        "skills": [],
        "tags": ["basic_magic_familiar"],
    },
    "final_banquet": {
        "template_id": "final_banquet",
        "name": "远方欢宴者与他的最终宴请",
        "stat_block": {
            "hp": 110,
            "atk": 10,
            "attack_dice": 10,
            "defense_dice": 0,
        },
        "actions": {
            "allow": ["pass", "attack", "dodge", "block", "offset"],
        },
        "skills": [],
        "tags": ["yellow_court_summon"],
    },
    "jade_lama": {
        "template_id": "jade_lama",
        "name": "翡翠喇嘛与求知高原",
        "stat_block": {
            "hp": 30,
            "atk": 30,
            "attack_dice": 10,
            "defense_dice": 10,
        },
        "actions": {
            "allow": ["pass", "attack", "dodge", "block", "offset"],
        },
        "skills": [],
        "tags": ["yellow_court_summon"],
    },
    "amber_elder": {
        "template_id": "amber_elder",
        "name": "琥珀长者与显秘神殿",
        "stat_block": {"hp": 40},
        "actions": {"allow": ["pass", "dodge", "block"]},
        "skills": [],
        "tags": ["yellow_court_summon"],
    },
    "plunderer": {
        "template_id": "plunderer",
        "name": "掠夺者",
        "stat_block": {
            "hp": 110,
            "atk": 30,
            "attack_dice": 10,
            "defense_dice": 0,
        },
        "actions": {
            "allow": ["pass", "attack", "dodge", "block", "offset"],
        },
        "skills": [],
        "tags": ["yellow_court_summon"],
    },
}


def _number(value, field, *, minimum=0):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"使魔{field}必须是数字")
    if value < minimum:
        raise ValueError(f"使魔{field}不能小于{minimum}")
    return value


def normalize_familiar_stat_block(raw_stat_block=None):
    """Expand a compact familiar stat block and validate its overrides."""
    raw = deepcopy(raw_stat_block or {})
    unknown = set(raw) - (set(DEFAULT_FAMILIAR_STAT_BLOCK) | {
        "attributes",
        "dice_overrides",
    })
    if unknown:
        raise ValueError(f"未知的使魔数值字段：{sorted(unknown)}")

    result = deepcopy(DEFAULT_FAMILIAR_STAT_BLOCK)
    result.update(raw)
    if result["source"] not in VALID_STAT_SOURCES:
        raise ValueError("使魔stat_block.source必须是fixed或summoner")
    if result["attack_type"] not in VALID_ATTACK_TYPES:
        raise ValueError("使魔attack_type必须是physical或magic")

    for field in ("hp", "mp", "atk", "attack_dice", "defense_dice"):
        _number(result[field], field)
    movement = result["movement"]
    if not isinstance(movement, int) or isinstance(movement, bool):
        raise TypeError("使魔movement必须是整数")
    if movement < 0:
        raise ValueError("使魔movement不能小于0")

    attributes = result.get("attributes", {})
    if not isinstance(attributes, dict):
        raise TypeError("使魔attributes必须是字典")
    unknown_attributes = set(attributes) - {
        "strength", "endurance", "flexibility", "magic", "fortune",
    }
    if unknown_attributes:
        raise ValueError(f"未知的使魔属性：{sorted(unknown_attributes)}")

    overrides = result.get("dice_overrides", {})
    if not isinstance(overrides, dict):
        raise TypeError("使魔dice_overrides必须是字典")
    unknown_dice = set(overrides) - VALID_DICE_OVERRIDES
    if unknown_dice:
        raise ValueError(f"未知的使魔派生骰：{sorted(unknown_dice)}")
    for name, value in overrides.items():
        _number(value, name)
    return result


def normalize_familiar_actions(raw_actions=None):
    result = deepcopy(DEFAULT_FAMILIAR_ACTIONS)
    result.update(deepcopy(raw_actions or {}))
    unknown = set(result) - {"allow", "deny"}
    if unknown:
        raise ValueError(f"未知的使魔行动权限字段：{sorted(unknown)}")
    for field in ("allow", "deny"):
        values = result[field]
        if not isinstance(values, (list, tuple, set)):
            raise TypeError(f"使魔actions.{field}必须是行动ID列表")
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"使魔actions.{field}只能包含非空行动ID")
        result[field] = set(values)
    return result


def validate_familiar_template(definition):
    required = {"template_id", "name"}
    missing = required - set(definition)
    if missing:
        raise ValueError(f"使魔模板缺少字段：{sorted(missing)}")
    normalize_familiar_stat_block(definition.get("stat_block"))
    normalize_familiar_actions(definition.get("actions"))
    if not isinstance(definition.get("skills", []), list):
        raise TypeError("使魔skills必须是列表")
    if not isinstance(definition.get("tags", []), list):
        raise TypeError("使魔tags必须是列表")
    return True


def get_familiar_template(template_id):
    try:
        definition = deepcopy(FAMILIAR_TEMPLATE_DATA[template_id])
    except KeyError as error:
        raise ValueError(f"未知的使魔模板：{template_id}") from error
    validate_familiar_template(definition)
    return definition


def register_familiar_template(template_id, definition, *, replace=False):
    """Register a GM/card-defined familiar template for later summons."""
    if not isinstance(template_id, str) or not template_id:
        raise ValueError("使魔模板ID必须是非空字符串")
    if template_id in FAMILIAR_TEMPLATE_DATA and not replace:
        raise ValueError(f"使魔模板已经存在：{template_id}")
    candidate = deepcopy(definition)
    candidate.setdefault("template_id", template_id)
    if candidate["template_id"] != template_id:
        raise ValueError("使魔模板字典键必须与template_id一致")
    validate_familiar_template(candidate)
    FAMILIAR_TEMPLATE_DATA[template_id] = candidate
    return get_familiar_template(template_id)


class Familiar(NPC):
    """A summoned NPC with template-defined stats and action permissions."""

    ZERO_DERIVED_DICE = {
        "physical_attack",
        "magic_attack",
        "dodge",
        "block",
        "offset",
    }

    def __init__(
        self,
        name,
        summoner,
        strength=1,
        endurance=1,
        flexibility=1,
        magic=1,
        fortune=1,
        *,
        hpmax=None,
        mpmax=0,
        move_conversion=1,
        derived_dice=None,
        atk=None,
        normal_attack_type="physical",
        action_permissions=None,
        template_id=None,
        tags=None,
    ):
        if summoner is None:
            raise ValueError("使魔必须具有召唤者")
        if normal_attack_type not in VALID_ATTACK_TYPES:
            raise ValueError("使魔普通攻击类型必须是physical或magic")
        self._familiar_hpmax_override = hpmax
        self._familiar_mpmax_override = mpmax
        self._familiar_atk_override = atk
        self._familiar_derived_dice = {
            dice_name: 0 for dice_name in self.ZERO_DERIVED_DICE
        }
        self._familiar_derived_dice.update(derived_dice or {})
        super().__init__(
            name,
            strength,
            endurance,
            flexibility,
            magic,
            fortune,
            move_conversion=move_conversion,
            initiative_anchor=summoner,
        )
        self.entity_type = "familiar"
        self.is_familiar = True
        self.summoner = summoner
        self.controller = getattr(summoner, "controller", summoner)
        self.normal_attack_type = normal_attack_type
        self.action_permissions = normalize_familiar_actions(
            action_permissions
        ) if action_permissions is not None else None
        self.familiar_template_id = template_id
        self.tags = set(tags or [])
        self.hp = self.hpmax
        self.mp = self.mpmax
        self.brink_of_death_counter = 0

    @property
    def hpmax(self):
        override = getattr(self, "_familiar_hpmax_override", None)
        if override is not None:
            return int(override)
        return super().hpmax

    @property
    def mpmax(self):
        override = getattr(self, "_familiar_mpmax_override", None)
        if override is not None:
            return int(override)
        return super().mpmax

    @property
    def atk(self):
        override = getattr(self, "_familiar_atk_override", None)
        if override is not None:
            return int(override) + self.atk_bonus
        return super().atk

    @property
    def normal_attack_damage(self):
        return self.atk

    def _derived_base_value(self, name):
        overrides = getattr(self, "_familiar_derived_dice", {})
        if name in overrides:
            return overrides[name]
        return super()._derived_base_value(name)

    def allows_action(self, action_id, *, skill_action=False):
        permissions = self.action_permissions
        if permissions is None:
            return True
        denied = permissions["deny"]
        if action_id in denied or (skill_action and "skill" in denied):
            return False
        # Loaded skills explicitly grant their own generated actions.  The
        # base allowlist controls only common ACTION_DATA commands.
        if skill_action:
            return True
        return action_id in permissions["allow"]

    def refresh_brink_of_death_availability(self):
        self.brink_of_death_counter = 0
        return False

    def is_alive(self):
        return self.hp > 0 and self.despawn_reason is None

    def die(self):
        """Familiars are destroyed without entering death or brink records."""
        game_manager = getattr(self, "game_manager", None)
        if game_manager is not None:
            return game_manager.despawn_character(self, reason="destroyed")
        self.hp = 0
        self.despawn_reason = "destroyed"
        self.status_flags.add("despawned")
        self.position = None
        return True


class FamiliarFactory:
    """Create or register a Familiar from one compact template."""

    @staticmethod
    def _attribute_values(stat_block, summoner):
        if stat_block["source"] == "summoner":
            values = {
                name: (
                    getattr(summoner, name).base_value,
                    getattr(summoner, name).base_plus,
                )
                for name in (
                    "strength", "endurance", "flexibility", "magic", "fortune",
                )
            }
        else:
            values = {
                "strength": 1,
                "endurance": 1,
                "flexibility": 1,
                "magic": 1,
                "fortune": 1,
            }
        values.update(stat_block.get("attributes", {}))
        return values

    @classmethod
    def create_from_definition(cls, definition, summoner, *, name=None):
        definition = deepcopy(definition)
        validate_familiar_template(definition)
        template_id = definition["template_id"]
        raw_stat_block = definition.get("stat_block", {})
        stat_block = normalize_familiar_stat_block(
            raw_stat_block
        )
        attributes = cls._attribute_values(stat_block, summoner)

        if stat_block["source"] == "summoner":
            inherited_values = {
                "hp": summoner.hpmax,
                "mp": summoner.mpmax,
                "atk": summoner.atk,
                "movement": getattr(summoner, "move_conversion", 0),
            }
            for field, value in inherited_values.items():
                if field not in raw_stat_block:
                    stat_block[field] = value

        attack_stat = (
            "magic_attack"
            if stat_block["attack_type"] == "magic"
            else "physical_attack"
        )
        derived_dice = {
            "physical_attack": 0,
            "magic_attack": 0,
            "dodge": stat_block["defense_dice"],
            "block": stat_block["defense_dice"],
            "offset": stat_block["defense_dice"],
        }
        derived_dice[attack_stat] = stat_block["attack_dice"]
        if stat_block["source"] == "summoner":
            derived_dice = {
                dice_name: getattr(summoner, dice_name)
                for dice_name in Familiar.ZERO_DERIVED_DICE
            }
            if "attack_dice" in raw_stat_block:
                derived_dice[attack_stat] = stat_block["attack_dice"]
            if "defense_dice" in raw_stat_block:
                for defense_name in ("dodge", "block", "offset"):
                    derived_dice[defense_name] = stat_block["defense_dice"]
        derived_dice.update(stat_block.get("dice_overrides", {}))

        familiar = Familiar(
            name or definition["name"],
            summoner,
            **attributes,
            hpmax=stat_block["hp"],
            mpmax=stat_block["mp"],
            move_conversion=stat_block["movement"],
            derived_dice=derived_dice,
            atk=stat_block["atk"],
            normal_attack_type=stat_block["attack_type"],
            action_permissions=definition.get("actions"),
            template_id=template_id,
            tags=definition.get("tags"),
        )
        for skill_definition in definition.get("skills", []):
            familiar.create_personal_skill(deepcopy(skill_definition))
        return familiar

    @classmethod
    def create(cls, template_id, summoner, *, name=None):
        return cls.create_from_definition(
            get_familiar_template(template_id),
            summoner,
            name=name,
        )

    @classmethod
    def spawn(
        cls,
        game_manager,
        template_id,
        summoner,
        position,
        *,
        name=None,
        activate_immediately=False,
        battle=None,
    ):
        familiar = cls.create(template_id, summoner, name=name)
        game_manager.register_character(
            familiar,
            position,
            activate_immediately=activate_immediately,
            battle=battle,
        )
        return familiar
