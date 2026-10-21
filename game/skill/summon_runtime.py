"""Runtime ownership, limits, replacement, and expiry for summoned familiars."""

from dataclasses import dataclass
from itertools import count

from game.character.familiar import FamiliarFactory, get_familiar_template
from game.turn.decision import DecisionOption, DecisionRequest


_SUMMON_SEQUENCE = count(1)


@dataclass(eq=False)
class SummonRecord:
    sequence: int
    familiar: object
    summoner: object
    template_id: str
    skill: object = None
    duration: object = None
    remove_with_source: bool = True
    active: bool = True
    removal_reason: str = None


class SummonManager:
    VALID_LIMIT_SCOPES = {"template", "skill", "summoner"}
    VALID_LIMIT_POLICIES = {"reject", "replace_oldest", "select"}

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.records = []

    def active_records(self, summoner, *, template_id=None, skill=None, scope="template"):
        records = [
            record
            for record in self.records
            if record.active
            and record.summoner is summoner
            and record.familiar in self.game_manager.characters
            and record.familiar.is_alive()
        ]
        if scope == "template":
            records = [
                record for record in records
                if record.template_id == template_id
            ]
        elif scope == "skill":
            records = [record for record in records if record.skill is skill]
        elif scope != "summoner":
            raise ValueError(f"未知的召唤上限范围：{scope}")
        return sorted(records, key=lambda record: record.sequence)

    def _select_replacements(
        self,
        records,
        count,
        summoner,
        decision_provider,
    ):
        if decision_provider is None:
            raise ValueError("select替换规则需要DecisionProvider")
        remaining = list(records)
        selected = []
        while len(selected) < count:
            chosen = decision_provider.choose(DecisionRequest(
                character=summoner,
                phase="召唤替换选择",
                prompt="选择一个要替换的现存使魔。",
                options=tuple(
                    DecisionOption(
                        record.familiar.name,
                        record,
                        (str(record.sequence),),
                    )
                    for record in remaining
                ),
            ))
            selected.append(chosen)
            remaining.remove(chosen)
        return selected

    def _prepare_capacity(
        self,
        summoner,
        template_id,
        skill,
        count,
        maximum_active,
        limit_scope,
        at_limit,
        decision_provider,
    ):
        if maximum_active is None:
            return []
        records = self.active_records(
            summoner,
            template_id=template_id,
            skill=skill,
            scope=limit_scope,
        )
        overflow = max(0, len(records) + count - maximum_active)
        if overflow == 0:
            return []
        if at_limit == "reject":
            raise ValueError("召唤数量将超过该效果规定的同时存在上限")
        if overflow > len(records):
            raise ValueError("召唤数量本身超过同时存在上限")
        if at_limit == "replace_oldest":
            return records[:overflow]
        return self._select_replacements(
            records,
            overflow,
            summoner,
            decision_provider,
        )

    @staticmethod
    def _instance_name(template_name, sequence, count, prefix=None):
        base = prefix or template_name
        if count == 1 and prefix is None:
            return base
        return f"{base}#{sequence}"

    def summon(
        self,
        summoner,
        template_id,
        position,
        *,
        skill=None,
        count=1,
        duration=None,
        maximum_active=None,
        limit_scope="template",
        at_limit="reject",
        activate_immediately=False,
        remove_with_source=True,
        name_prefix=None,
        decision_provider=None,
    ):
        if summoner not in self.game_manager.characters or not summoner.is_alive():
            raise ValueError("只有本局存活角色可以召唤使魔")
        if position is None:
            raise ValueError("召唤必须具有出现位置")
        definition = get_familiar_template(template_id)
        replacements = self._prepare_capacity(
            summoner,
            template_id,
            skill,
            count,
            maximum_active,
            limit_scope,
            at_limit,
            decision_provider,
        )
        for record in replacements:
            self.remove(record, reason="summon_replaced")

        created = []
        for _index in range(count):
            sequence = next(_SUMMON_SEQUENCE)
            name = self._instance_name(
                definition["name"],
                sequence,
                count,
                name_prefix,
            )
            familiar = FamiliarFactory.spawn(
                self.game_manager,
                template_id,
                summoner,
                position,
                name=name,
                activate_immediately=activate_immediately,
            )
            record = SummonRecord(
                sequence=sequence,
                familiar=familiar,
                summoner=summoner,
                template_id=template_id,
                skill=skill,
                duration=duration,
                remove_with_source=bool(remove_with_source),
            )
            familiar.summon_record = record
            self.records.append(record)
            created.append(record)
        return {"records": created, "replaced": replacements}

    def remove(self, record, reason="summon_expired"):
        if record not in self.records or not record.active:
            return False
        record.active = False
        record.removal_reason = reason
        if record.familiar in self.game_manager.characters:
            self.game_manager.despawn_character(
                record.familiar,
                reason=reason,
            )
        return True

    def on_character_removed(self, character, reason="external"):
        record = getattr(character, "summon_record", None)
        if record in self.records and record.active:
            record.active = False
            record.removal_reason = reason
        return record

    def remove_for_source(self, skill):
        removed = []
        for record in list(self.records):
            if record.active and record.skill is skill and record.remove_with_source:
                self.remove(record, reason="summon_source_removed")
                removed.append(record)
        return removed

    def end_turn(self, _turn_number):
        expired = []
        for record in list(self.records):
            if not record.active or record.duration is None:
                continue
            record.duration -= 1
            if record.duration <= 0:
                self.remove(record, reason="summon_expired")
                expired.append(record)
        return expired
