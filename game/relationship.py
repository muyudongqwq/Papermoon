from dataclasses import dataclass, field
from enum import Enum


class Attitude(str, Enum):
    HOSTILE = "hostile"
    NEUTRAL = "neutral"
    FRIENDLY = "friendly"


def normalize_attitude(value):
    if isinstance(value, Attitude):
        return value
    try:
        return Attitude(str(value).lower())
    except ValueError as exc:
        raise ValueError(f"未知态度：{value}") from exc


@dataclass(eq=False)
class Alliance:
    alliance_id: str
    founders: tuple
    members: list
    betrayal_rules: tuple = ()
    known_by: set = field(default_factory=set)
    created_turn: int = 0
    active: bool = True

    def __post_init__(self):
        if not self.alliance_id:
            raise ValueError("同盟必须提供alliance_id")
        self.members = list(dict.fromkeys(self.members))
        self.founders = tuple(dict.fromkeys(self.founders))
        if len(self.members) < 2:
            raise ValueError("同盟建立时至少需要两名成员")
        self.betrayal_rules = tuple(self.betrayal_rules or ())
        self.known_by.update(self.members)

    @property
    def ally_source(self):
        return ("alliance", self.alliance_id)


@dataclass
class AllianceInvitation:
    inviter: object
    invitee: object
    alliance_id: str
    betrayal_rules: tuple = ()
    submitted_turn: int = 0
    accepted: bool = False


@dataclass
class AllianceJoinApplication:
    applicant: object
    alliance: Alliance
    contact_member: object
    submitted_turn: int
    sequence: int


@dataclass(eq=False)
class TrapInformation:
    """Minimal persistent knowledge contract for the future trap runtime."""

    trap_id: str
    owner: object
    position: object
    share_with_links: bool = True
    known_by: set = field(default_factory=set)
    active: bool = True

    def __post_init__(self):
        if not self.trap_id:
            raise ValueError("陷阱必须提供trap_id")
        if self.owner is None or self.position is None:
            raise ValueError("陷阱必须提供所有者和位置")
        self.known_by.add(self.owner)


@dataclass(frozen=True)
class TemporaryInformation:
    """One turn-scoped fact which has mechanical meaning for one recipient."""

    information_type: str
    recipient: object
    turn_number: int
    source: object = None
    position: object = None
    data: dict = field(default_factory=dict)


class InformationManager:
    """Only the mechanical information that the engine must remember."""

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.traps = []
        self.temporary_information = []

    def begin_turn(self, turn_number):
        """Expire temporary facts from earlier global turns."""
        turn_number = int(turn_number)
        self.temporary_information[:] = [
            information
            for information in self.temporary_information
            if information.turn_number >= turn_number
        ]
        return True

    def record_temporary_information(
        self,
        information_type,
        recipient,
        *,
        source=None,
        position=None,
        turn_number=None,
        data=None,
    ):
        if recipient is None:
            raise ValueError("临时情报必须指定接收者")
        if turn_number is None:
            turn_number = self.game_manager.turn_manager.turn
        information = TemporaryInformation(
            str(information_type),
            recipient,
            int(turn_number),
            source,
            position,
            dict(data or {}),
        )
        self.temporary_information.append(information)
        return information

    def record_direct_attack_source(self, attacker, recipient, position):
        """Tell one attacked character where a direct attack originated."""
        if attacker is None or position is None:
            raise ValueError("超距打击来源情报必须包含攻击者与来源位置")
        return self.record_temporary_information(
            "direct_attack_source",
            recipient,
            source=attacker,
            position=position,
        )

    def get_temporary_information(
        self,
        recipient,
        *,
        information_type=None,
        turn_number=None,
    ):
        records = [
            information
            for information in self.temporary_information
            if information.recipient is recipient
        ]
        if information_type is not None:
            records = [
                information
                for information in records
                if information.information_type == information_type
            ]
        if turn_number is not None:
            records = [
                information
                for information in records
                if information.turn_number == int(turn_number)
            ]
        return records

    def register_trap_information(
        self,
        trap_id,
        owner,
        position,
        *,
        share_with_links=True,
    ):
        if any(trap.trap_id == trap_id for trap in self.traps):
            raise ValueError(f"陷阱ID已存在：{trap_id}")
        trap = TrapInformation(
            trap_id,
            owner,
            position,
            bool(share_with_links),
        )
        self.traps.append(trap)
        self.refresh_trap_sharing()
        return trap

    def learn_trap(self, character, trap):
        if trap not in self.traps:
            raise ValueError("陷阱情报不属于本局")
        trap.known_by.add(character)
        return True

    def knows_trap(self, character, trap):
        return trap in self.traps and character in trap.known_by

    def refresh_trap_sharing(self):
        for trap in self.traps:
            if not trap.active or not trap.share_with_links:
                continue
            # This group deliberately excludes ordinary Alliance allies.
            # It contains only Master/Servant, summoner/familiar and current
            # travel companions, and it never recursively retransmits.
            trap.known_by.update(trap.owner.get_shared_vision_group())
        return True

    def deactivate_trap(self, trap):
        if trap not in self.traps:
            raise ValueError("陷阱情报不属于本局")
        trap.active = False
        return True


class RelationshipManager:
    """Game-wide attitudes, ally sources, and leaderless alliances."""

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.alliances = []
        self.invitations = []
        self.pending_creations = []
        self.pending_joins = []
        self.pending_exits = []
        self.pending_attitudes = {}
        self.betrayal_records = []
        self._application_sequence = 0

    @property
    def turn(self):
        return self.game_manager.turn_manager.turn

    def get_alliance(self, alliance_id):
        return next(
            (
                alliance
                for alliance in self.alliances
                if alliance.active and alliance.alliance_id == alliance_id
            ),
            None,
        )

    def queue_attitude(self, source, target, attitude):
        if source is target:
            raise ValueError("不能设置角色对自身的态度")
        attitude = normalize_attitude(attitude)
        self.pending_attitudes[(source, target)] = attitude
        return attitude

    def force_hostile(self, source, target):
        self.pending_attitudes.pop((source, target), None)
        source.set_base_attitude(target, Attitude.HOSTILE)
        return Attitude.HOSTILE

    def force_mutual_hostile(self, first, second):
        self.force_hostile(first, second)
        self.force_hostile(second, first)
        return True

    def invite_alliance(
        self,
        inviter,
        invitee,
        alliance_id,
        betrayal_rules=(),
    ):
        if inviter is invitee:
            raise ValueError("不能邀请自己建立同盟")
        if (
            not inviter.is_alive()
            or not invitee.is_alive()
            or inviter.position is None
            or inviter.position is not invitee.position
        ):
            raise ValueError("建立同盟邀请时双方必须存活并位于同一节点")
        if not (
            inviter.is_friendly_with(invitee)
            and invitee.is_friendly_with(inviter)
        ):
            raise ValueError("建立同盟前双方必须互为友善或盟友")
        if self.get_alliance(alliance_id) is not None or any(
            invitation.alliance_id == alliance_id
            for invitation in self.invitations + self.pending_creations
        ):
            raise ValueError(f"同盟ID已存在：{alliance_id}")
        invitation = AllianceInvitation(
            inviter,
            invitee,
            alliance_id,
            tuple(betrayal_rules or ()),
            self.turn,
        )
        self.invitations.append(invitation)
        return invitation

    def accept_invitation(self, invitation, character):
        if invitation not in self.invitations:
            raise ValueError("结盟邀请不存在或已经失效")
        if invitation.invitee is not character:
            raise ValueError("只有被邀请者可以接受结盟邀请")
        if not character.is_alive() or not invitation.inviter.is_alive():
            raise ValueError("死亡或退场角色不能建立同盟")
        invitation.accepted = True
        self.invitations.remove(invitation)
        self.pending_creations.append(invitation)
        return True

    def reveal_alliance(self, alliance, character):
        if alliance not in self.alliances or not alliance.active:
            raise ValueError("同盟不存在")
        alliance.known_by.add(character)
        return True

    def apply_to_alliance(self, applicant, alliance, contact_member):
        if alliance not in self.alliances or not alliance.active:
            raise ValueError("同盟不存在")
        if applicant not in alliance.known_by:
            raise ValueError("申请者不知道该同盟存在")
        if applicant in alliance.members:
            raise ValueError("申请者已经是该同盟成员")
        if contact_member not in alliance.members:
            raise ValueError("接触角色不是该同盟成员")
        if (
            applicant.position is None
            or applicant.position is not contact_member.position
        ):
            raise ValueError("申请者必须与至少一名同盟成员位于同一节点")
        if not self._friendly_with_all(applicant, alliance.members):
            raise ValueError("申请者未与全部同盟成员互为友善或盟友")
        self._application_sequence += 1
        application = AllianceJoinApplication(
            applicant,
            alliance,
            contact_member,
            self.turn,
            self._application_sequence,
        )
        self.pending_joins.append(application)
        return application

    def request_exit(self, character, alliance):
        if alliance not in self.alliances or character not in alliance.members:
            raise ValueError("角色不是该同盟成员")
        item = (character, alliance)
        if item not in self.pending_exits:
            self.pending_exits.append(item)
        return True

    def _friendly_with_all(self, character, members):
        return all(
            character.is_friendly_with(member)
            and member.is_friendly_with(character)
            for member in members
            if member is not character
        )

    def prepare_join_relationships(self, decision_provider=None):
        """At turn end, let simultaneous applicants consent to friendliness."""
        from game.turn.decision import DecisionOption, DecisionRequest

        grouped = {}
        for application in self.pending_joins:
            grouped.setdefault(application.alliance, []).append(application)
        results = []
        for applications in grouped.values():
            applications.sort(key=lambda item: item.sequence)
            applicants = [item.applicant for item in applications]
            for index, first in enumerate(applicants):
                for second in applicants[index + 1:]:
                    if (
                        first.is_friendly_with(second)
                        and second.is_friendly_with(first)
                    ):
                        continue
                    if decision_provider is None:
                        results.append((first, second, False))
                        continue
                    first_agrees = decision_provider.choose(DecisionRequest(
                        character=first,
                        phase="同盟申请关系确认",
                        prompt=f"{second.name}也在申请同一同盟。是否互相提升为友善？",
                        options=(
                            DecisionOption("同意", True, ("yes", "同意")),
                            DecisionOption("拒绝", False, ("no", "拒绝")),
                        ),
                    ))
                    second_agrees = decision_provider.choose(DecisionRequest(
                        character=second,
                        phase="同盟申请关系确认",
                        prompt=f"{first.name}也在申请同一同盟。是否互相提升为友善？",
                        options=(
                            DecisionOption("同意", True, ("yes", "同意")),
                            DecisionOption("拒绝", False, ("no", "拒绝")),
                        ),
                    ))
                    agreed = bool(first_agrees and second_agrees)
                    if agreed:
                        self.queue_attitude(first, second, Attitude.FRIENDLY)
                        self.queue_attitude(second, first, Attitude.FRIENDLY)
                    results.append((first, second, agreed))
        return results

    def apply_turn_start(self):
        for (source, target), attitude in list(self.pending_attitudes.items()):
            if source.is_alive() and target.is_alive():
                source.set_base_attitude(target, attitude)
        self.pending_attitudes.clear()

        for character, alliance in list(self.pending_exits):
            if alliance.active and character in alliance.members:
                self._remove_member(alliance, character)
        self.pending_exits.clear()

        for invitation in list(self.pending_creations):
            if not invitation.inviter.is_alive() or not invitation.invitee.is_alive():
                continue
            alliance = Alliance(
                invitation.alliance_id,
                (invitation.inviter, invitation.invitee),
                [invitation.inviter, invitation.invitee],
                invitation.betrayal_rules,
                created_turn=self.turn,
            )
            self.alliances.append(alliance)
            self._refresh_alliance_sources(alliance)
        self.pending_creations.clear()

        applications = sorted(
            self.pending_joins,
            key=lambda item: item.sequence,
        )
        self.pending_joins.clear()
        for application in applications:
            alliance = application.alliance
            applicant = application.applicant
            if (
                not alliance.active
                or not applicant.is_alive()
                or applicant in alliance.members
                or not self._friendly_with_all(applicant, alliance.members)
            ):
                continue
            alliance.members.append(applicant)
            alliance.known_by.update(alliance.members)
            self._refresh_alliance_sources(alliance)
        return True

    def _refresh_alliance_sources(self, alliance):
        source = alliance.ally_source
        for index, first in enumerate(alliance.members):
            for second in alliance.members[index + 1:]:
                first.add_ally(second, source=source)
                first.ensure_friendly_base(second)
                second.ensure_friendly_base(first)

    def _remove_member(self, alliance, character):
        if character not in alliance.members:
            return False
        source = alliance.ally_source
        others = [member for member in alliance.members if member is not character]
        for other in others:
            character.remove_ally(other, source=source)
            character.ensure_friendly_base(other)
            other.ensure_friendly_base(character)
        alliance.members.remove(character)
        if len(alliance.members) <= 1:
            self._dissolve(alliance)
        return True

    def _dissolve(self, alliance):
        source = alliance.ally_source
        for index, first in enumerate(alliance.members):
            for second in alliance.members[index + 1:]:
                first.remove_ally(second, source=source)
        alliance.active = False
        return True

    def betray(self, attacker, target, *, reason="attack"):
        shared = [
            alliance
            for alliance in self.alliances
            if alliance.active
            and attacker in alliance.members
            and target in alliance.members
        ]
        records = []
        for alliance in shared:
            record = {
                "turn": self.turn,
                "attacker": attacker,
                "target": target,
                "alliance": alliance,
                "rules": alliance.betrayal_rules,
                "reason": reason,
            }
            self.betrayal_records.append(record)
            records.append(record)
            self._remove_member(alliance, attacker)

        # Natural ally sources are relations, not contracts; breaking them does
        # not alter master/servant or summoner/familiar ownership fields.
        for source in list(attacker.get_ally_sources(target)):
            if not (isinstance(source, tuple) and source[:1] == ("alliance",)):
                attacker.remove_ally(target, source=source)
        attacker.set_base_attitude(target, Attitude.FRIENDLY)
        self.force_hostile(target, attacker)
        return records

    def resolve_attack_attitude(
        self,
        attacker,
        target,
        decision_provider=None,
    ):
        """Apply hostility/betrayal when an attack is irrevocably committed."""
        if attacker is None or target is None or attacker is target:
            return True
        battle = getattr(attacker, "current_battle", None)
        if (
            battle is not None
            and battle is getattr(target, "current_battle", None)
            and not battle.ended
        ):
            battle.add_combat_link(attacker, target, source="attack")
        if attacker.is_ally(target):
            consented = False
            if decision_provider is not None:
                from game.turn.decision import DecisionOption, DecisionRequest

                consented = bool(decision_provider.choose(DecisionRequest(
                    character=target,
                    phase="盟友受击确认",
                    prompt=(
                        f"{attacker.name}正在攻击你。是否同意此次攻击且不产生敌意？"
                    ),
                    options=(
                        DecisionOption("同意", True, ("yes", "同意")),
                        DecisionOption("拒绝", False, ("no", "拒绝")),
                    ),
                )))
            if not consented:
                self.betray(attacker, target, reason="attack")
            return True
        self.force_hostile(target, attacker)
        return True

