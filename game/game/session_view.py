"""Build JSON-compatible views on the session's engine thread."""

from game.game.character_state import character_state


def current_known_characters(owned, characters):
    known = set(owned)
    for actor in owned:
        known.update(actor.current_awareness(characters))
    return known.intersection(characters)


def redact_status_sources(value, known):
    """Keep full provenance in GM records, without revealing an unknown caster."""
    known_ids = {character.character_id for character in known}
    def redact(item):
        if isinstance(item, dict):
            if "status_id" in item and "source_character_id" in item and item["source_character_id"] not in known_ids:
                for key in ("source_character_id", "source_name", "source_skill_id"):
                    item[key] = None
            for child in item.values():
                redact(child)
        elif isinstance(item, list):
            for child in item:
                redact(child)
    redact(value)
    return value


def character_view(character, position_id, *, exact):
    view = {
        "character_id": character.character_id,
        "name": character.name,
        "entity_type": character.entity_type,
        "position_id": position_id(character.position),
    }
    if exact:
        view.update(
            hp=character.hp, hpmax=character.hpmax,
            mp=character.mp, mpmax=character.mpmax,
            temporary_mp=character.temporary_mp,
            action_point=character.action_point,
            in_battle=character.in_battle,
            statuses=sorted(character.status_flags),
            attributes={name: getattr(character, name).value
                        for name in character.ATTRIBUTE_NAMES},
            resources={key: resource.current_value
                       for key, resource in character.resources.items()},
        )
        if hasattr(character, "command_spell"):
            view["command_spell"] = character.command_spell
        view.update(character_state(character))
        manager = getattr(character, "game_manager", None)
        view["fields"] = [{"field_id": field.field_id, "name": field.name,
                           "position_id": position_id(field.center), "duration": field.duration,
                           "battle_id": getattr(field.bound_battle, "battle_id", None)}
                          for field in getattr(getattr(manager, "field_manager", None), "fields", [])
                          if field.owner is character and not field.removed]
    return view


def build_snapshot(session, controller_id):
    game = session.game_manager
    gm = controller_id == session.gm_id
    characters = session._characters()
    owned = [character for character in characters
             if session._controller_for(character) == controller_id]
    visible = current_known_characters(owned, characters)
    nodes = set()
    for actor in owned:
        nodes.update(actor.seen_locations)
        if actor.position is not None:
            nodes.add(actor.position)
    if gm:
        visible.update(characters)
        nodes.update(game.get_map_nodes(merge_area_levels=False))
    # Perception conveys current known positions, never enemy resources.
    visible.intersection_update(characters)
    views = []
    for character in characters:
        if character not in visible:
            continue
        exact = gm or character in owned
        position = character.position
        if position is not None:
            nodes.add(position)
        view = character_view(character, session._position_id, exact=exact)
        if not gm:
            redact_status_sources(view, visible)
        view["position_id"] = session._position_id(position)
        views.append(view)
    map_views = [{"position_id": session._position_id(node), "name": node.name}
                 for node in nodes]
    map_views.sort(key=lambda node: node["position_id"])
    battles = []
    for battle in game.turn_manager.battles:
        participants = [actor.character_id for actor in battle.participants if actor in visible]
        if gm or participants:
            battles.append({"battle_id": battle.battle_id, "participants": participants, "ended": battle.ended,
                            "phase": battle.current_phase,
                            "current_character_id": (battle.current_character.character_id
                                if battle.current_character in visible else None)})
    decision = session.decision_provider.current(controller_id)
    snapshot = {
        "session_id": session.session_id,
        "controller_id": controller_id,
        "state": session._state,
        "turn": game.turn_manager.turn,
        "ap_layer": game.turn_manager.current_ap_layer,
        "phase": decision["phase"] if decision is not None else session._state,
        "decision": decision,
        "controlled_character_ids": [actor.character_id for actor in owned],
        "characters": views,
        "positions": map_views,
        "battles": battles,
        "result": session._result,
    }
    if gm:
        snapshot["error"] = session._error
    return snapshot
