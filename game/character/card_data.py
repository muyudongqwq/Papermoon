"""Reviewed card templates; skill effects remain in the content catalogs.

Card IDs identify templates. Character.character_id identifies each new entity.
Text files in samples are provenance, not executable card definitions.
"""


CHARACTER_CARD_DATA = {
    "servant_test_0": {
        "card_id": "servant_test_0",
        "character_type": "servant",
        "name": "尼禄·克劳狄乌斯·凯萨·奥古斯都·日耳曼尼库斯",
        "source": "test_examples/samples/Servant_test_0.txt",
        "attributes": {"strength": 2, "endurance": 2, "flexibility": 5, "magic": 4, "fortune": 2},
        "servant_class": "Archer",
        "noble": {"rank": "A", "plus": 1},
        "class_skills": [],
        "personal_skills": ["servant_test_0:imperial_privilege", "servant_test_0:setting_sun", "servant_test_0:headache"],
        "basic_magics": [],
        "noble_phantasms": ["servant_test_0:golden_theatre", "servant_test_0:original_fire", "servant_test_0:laus_saint_claudius"],
    },
    "master_test_0": {
        "card_id": "master_test_0",
        "character_type": "master",
        "name": "莱昂纳多·达·芬奇",
        "source": "test_examples/samples/Master_test_0.txt",
        "attributes": {
            "strength": 1,
            "endurance": 1,
            "flexibility": 1,
            "magic": {"value": 5, "plus": 2},
            "fortune": 3,
        },
        "talent": "A",
        "command_spell": 3,
        "class_skills": [],
        "personal_skills": [
            "master_test_0:unblemished_person",
            "master_test_0:world_faith_domination",
            "master_test_0:starfire",
        ],
        "basic_magics": ["healing", "workshop"],
        "noble_phantasms": [],
    },
    "archer_alpha_test": {
        "card_id": "archer_alpha_test",
        "character_type": "servant",
        "name": "迦尔纳",
        "source": "test_examples/samples/alphatest/Archer_alpha_test.txt",
        # 卡面显示E、实际按A加骰；显示伪装暂由GM说明。
        "attributes": {"strength": 5, "endurance": {"value": 3, "plus": 1},
                       "flexibility": {"value": 5, "plus": 1}, "magic": 4, "fortune": 5},
        "servant_class": "Archer",
        "noble": "C",
        "class_skills": [{"name": "对魔力", "rank": "A"}, {"name": "单独行动", "rank": "C"}],
        "personal_skills": [
            "archer_alpha_test:uncrowned_arms",
            "archer_alpha_test:divinity",
            "archer_alpha_test:vaikarthana",
        ],
        "basic_magics": [],
        "noble_phantasms": [
            "archer_alpha_test:bhargavastra",
            "archer_alpha_test:kavacha_and_kundala",
        ],
    },
    "lancer_alpha_test": {
        "card_id": "lancer_alpha_test",
        "character_type": "servant",
        "name": "项羽",
        "source": "test_examples/samples/alphatest/Lancer_alpha_test.txt",
        "attributes": {"strength": 5, "endurance": 5, "flexibility": 4, "magic": 3, "fortune": 2},
        "servant_class": "Lancer",
        "noble": "C",
        "class_skills": [{"name": "对魔力", "rank": "E"}, {"name": "骑乘", "rank": "A"}],
        "personal_skills": [
            "lancer_alpha_test:mystic_eyes",
            "lancer_alpha_test:might",
            "lancer_alpha_test:last_stand",
        ],
        "basic_magics": [],
        "noble_phantasms": [
            "lancer_alpha_test:overlord_spear",
            "lancer_alpha_test:spear_king_annihilation",
        ],
    },
}
