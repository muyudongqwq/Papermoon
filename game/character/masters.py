from game.rank.rank import FixedRank
from .character import Character

class Master(Character):

    def __init__(self, name, strength, endurance, flexibility, magic, fortune, talent, command_spell):
        #初始化character部分
        super().__init__(name, strength, endurance, flexibility, magic, fortune)
        #把character.py里的东西继承下来

        self.talent = FixedRank(talent, allow_plus=False)
        self.command_spell = command_spell

        self.magic_skill = []
        self.mystic_code = []
        self.status_flags = set()

        self.servants = []
        # 兼容旧名称；该字段现在与servants指向同一列表。
        self.servant = self.servants

        self.resting = False
        self.rest_turns = 0
        self.rest_started_turn = None
        self.last_rest_started_turn = None
        self.rest_scheduled_turn = None
        self.command_spell_transfer = None

        #1行动点=2移动力
        self.move_conversion = 2
        self.entity_type = "master"

    def add_servant(self, servant):
        if servant in self.servants:
            return True
        if len(self.servants) >= 2:
            return False

        old_master = getattr(servant, "master", None)
        if old_master is not None and old_master is not self:
            old_master.remove_servant(
                servant,
                trigger_master_lost=False,
            )

        self.servants.append(servant)
        servant.master = self
        self.add_ally(servant, source=("master_servant", id(self)))
        return True

    def remove_servant(self, servant, trigger_master_lost=True):
        if servant not in self.servants:
            return False
        self.servants.remove(servant)
        if getattr(servant, "master", None) is self:
            servant.master = None
            if trigger_master_lost and servant.is_alive():
                servant.trigger_class_skill_event(
                    "master_lost",
                    turn_number=servant.current_global_turn,
                )
        return True

    def can_start_rest(self, turn_number):
        if self.last_rest_started_turn is None:
            return True
        return turn_number - self.last_rest_started_turn >= 12

    def finish_rest(self, recover=True):
        completed_turns = self.rest_turns
        recovered_hp = 0
        recovered_mp = 0
        if recover and completed_turns > 0 and self.is_alive():
            recovered_hp = self.recover_resource(
                "hp",
                self.hpmax * 0.25 * completed_turns,
            )
            recovered_mp = self.recover_resource(
                "mp",
                self.mpmax * 0.25 * completed_turns,
            )
        self.resting = False
        self.rest_turns = 0
        self.rest_started_turn = None
        self.rest_scheduled_turn = None
        return {
            "completed_turns": completed_turns,
            "recovered_hp": recovered_hp,
            "recovered_mp": recovered_mp,
        }

    def cancel_rest(self):
        return self.finish_rest(recover=True)

    def end_global_turn(self, turn_number):
        super().end_global_turn(turn_number)
        if not self.resting or self.rest_scheduled_turn != turn_number:
            return
        if self.in_battle or self.position is None or not self.position.is_building:
            self.cancel_rest()
            return

        self.rest_turns += 1
        self.rest_scheduled_turn = None
        if self.rest_turns >= 4:
            self.finish_rest()

    def die(self):
        self.finish_rest(recover=False)
        for servant in self.servants[:]:
            self.remove_servant(servant)
        super().die()

    def show_extra_status(self):
        print(f"天赋：{self.talent}")
        return super().show_extra_status()

    def show_command_spell(self):
        print(f"令咒数量：{self.command_spell}")
        return super().show_command_spell()

    def show_basic_magics(self):
        print("基础魔术：")
        print("这里大概要写基础魔术以及效果。")


#测试用例
if __name__ == "__main__":
    A = Master(
         name= "TEST",
         strength= 5,
         endurance= (4,1),
         flexibility= 3,
         magic= 2,
         fortune= 8,
         talent= "C",

         command_spell = 3
    )

    A.show_status()
    print("测试结束")
