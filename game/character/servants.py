from game.rank.rank import FixedRank
from .character import Character

VALID_SERVANT_CLASSES = ["Saber", "Archer", "Lancer", "Rider", "Caster", "Assassin", "Berserker", "Ruler", "Avenger", "Pretender", "Beast", "Savior", "MoonCancer"]
class Servant(Character):

    def __init__(self, name, strength, endurance, flexibility, magic, fortune, servant_class, noble):
        #初始化character部分
        super().__init__(name, strength, endurance, flexibility, magic, fortune)
        #把character.py里的东西继承下来

        self.servant_class = servant_class
        self.noble = FixedRank(noble, allow_plus = True)

        self.class_skills = []
        self.personal_skills = []
        self.noble_phantasms = []

        self.master = None
        #1行动点=3移动力（节点地图）
        self.move_conversion = 3
        self.status_flags = set()
        self.entity_type = "servant"

        self.validate_class()
        self.validate_noble_number()
#        self.show_class_skill()

    def set_master(self, master):
        return master.add_servant(self)

    def add_class_skill(self, name, rank):
        from game.skill.skill_runtime import load_class_skill

        return load_class_skill(self, name, rank)

    def create_noble_phantasm(self, definition):
        from game.skill.skill_runtime import create_noble_phantasm

        return create_noble_phantasm(self, definition)

    def trigger_class_skill_event(self, event_name, **context):
        from game.skill.skill_runtime import trigger_skill_event

        return trigger_skill_event(self, event_name, **context)

    def clear_master(self):
        if self.master is None:
            return False
        return self.master.remove_servant(self)

    def get_available_mp(self):
        master_mp = 0
        if self.master is not None and self.master.is_alive():
            master_mp = self.master.get_available_mp()
        return self.temporary_mp + self.mp + master_mp

    def consume_mp(self, amount):
        return self.pay_mp_with_ledger(amount) is not None

    def pay_mp_with_ledger(self, amount):
        if amount < 0:
            raise ValueError("MP不会小于0")
        amount = int(amount)
        if self.get_available_mp() < amount:
            return None

        temporary_cost = min(self.temporary_mp, amount)
        amount -= temporary_cost
        servant_cost = min(self.mp, amount)
        master_cost = amount - servant_cost
        self.temporary_mp -= temporary_cost
        self.mp -= servant_cost
        from game.game.rule_report import report_mp_pool_change
        report_mp_pool_change(self, "temporary_mp", self.temporary_mp + temporary_cost,
                              self.temporary_mp, operation="subtract", reason="pay_temporary_mp")
        report_mp_pool_change(self, "mp", self.mp + servant_cost, self.mp,
                              operation="subtract", reason="pay")
        battle = getattr(self, "current_battle", None)
        if battle is not None and not getattr(battle, "ended", False):
            if temporary_cost:
                battle.record_mp_payment(self, temporary_cost, "temporary_mp")
            if servant_cost:
                battle.record_mp_payment(self, servant_cost, "mp")
        ledger = []
        if temporary_cost:
            ledger.append({
                "payer": self,
                "amount": temporary_cost,
                "pool": "temporary_mp",
            })
        if servant_cost:
            ledger.append({"payer": self, "amount": servant_cost, "pool": "mp"})
        if master_cost:
            master_ledger = self.master.pay_mp_with_ledger(master_cost)
            if master_ledger is None:
                # Availability was checked above; this guards state corruption.
                raise RuntimeError("御主MP支付状态在结算中发生变化")
            ledger.extend(master_ledger)
            if battle is not None and getattr(self.master, "current_battle", None) is not battle:
                for payment in master_ledger:
                    battle.record_mp_payment(
                        payment["payer"], payment["amount"], payment.get("pool", "mp")
                    )
        return ledger

    def end_global_turn(self, turn_number):
        super().end_global_turn(turn_number)
        if not self.is_alive():
            return
        if self.master is not None and not self.master.is_alive():
            self.clear_master()
        if self.master is not None:
            return

        upkeep = self.modifier_manager.calculate_cost(
            90,
            resource="mp",
            cost_id="masterless_upkeep",
        )
        old_mp = self.mp
        self.mp = max(0, self.mp - upkeep)
        from game.game.rule_report import report_mp_pool_change
        report_mp_pool_change(self, "mp", old_mp, self.mp,
                              operation="subtract", reason="masterless_upkeep")
        self.update_modifiers(
            "masterless_upkeep_end",
            turn_number=turn_number,
        )
        if self.mp == 0:
            self.die()

    def die(self):
        if self.master is not None:
            self.master.remove_servant(self, trigger_master_lost=False)
        super().die()

    def show_extra_status(self):
        print(f"宝具：{self.noble}")
        return super().show_extra_status()

    def show_class(self):
        visibility = self.format_non_ally_visibility()
        print(
            f"职介：{self.servant_class}"
            f"{visibility}"
        )
        return super().show_class()

    def show_class_skill(self):
        print(f"职介技能")
        print(f"")
        return super().show_class_skill()
#==================================================================
#检查职介对不对
    def validate_class(self):
        if self.servant_class not in VALID_SERVANT_CLASSES: raise ValueError(f"职介不正确：{self.servant_class}！需且仅需首字母大写。")
#检查宝具数量
    def validate_noble_number(self):
        limit = 2

        if self.noble.plus == 1: limit = 3
        if len(self.noble_phantasms) > limit: raise ValueError("宝具多了")

