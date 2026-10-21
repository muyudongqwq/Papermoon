class ActionResolver:
    def resolve(self, action, decision_provider=None):
        from game.skill.skill_action import SkillAction

        game_manager = getattr(action.actor, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is not None:
            declared = event_manager.emit(
                "action_declared",
                timing="before",
                actor=action.actor,
                source=action,
                target=getattr(action, "target", None),
                phase=getattr(action, "definition", {}).get(
                    "resolution_timing",
                    "action",
                ),
                battle=getattr(action.actor, "current_battle", None),
                position=getattr(action.actor, "position", None),
                payload={"action_id": action.action_id},
                decision_provider=decision_provider,
            )
            if declared.cancelled:
                action.ignored = True
                action.ignored_reason = "cancelled_by_event"
                return False

        active_transfer = getattr(
            action.actor,
            "command_spell_transfer",
            None,
        )
        if (
            active_transfer is not None
            and action.action_id != "command_spell_transfer"
        ):
            game_manager = getattr(action.actor, "game_manager", None)
            if game_manager is not None:
                game_manager.command_spell_transfer_manager.interrupt(
                    active_transfer,
                    f"other_action:{action.action_id}",
                )

        if (
            getattr(action.actor, "casting_state", None) is not None
            and action.action_id
            not in {
                "chant",
                "release",
                "interrupt_casting",
                # direct_attack只是打开虚拟攻击阶段；真正选择的行动
                # 再决定继续、解放或中断咏唱。
                "direct_attack",
            }
        ):
            action.actor.interrupt_casting(
                reason=f"other_action:{action.action_id}"
            )

        if isinstance(action, SkillAction):
            result = action.resolve(decision_provider)

        elif action.action_id == "move":result = action.move()

        elif action.action_id == "pass":result = action.pass_action()

        elif action.action_id == "investigate":result = action.investigate(decision_provider)

        elif action.action_id == "perceive":result = action.perceive()

        elif action.action_id == "battle_perceive":result = action.battle_perceive()

        elif action.action_id == "hide":result = action.hide()

        elif action.action_id == "stay":result = action.stay()

        elif action.action_id == "attack":result = action.attack(decision_provider)

        elif action.action_id == "direct_attack":result = action.direct_attack(decision_provider)

        elif action.action_id == "mend":result = action.mend()

        elif action.action_id == "rest":result = action.rest()

        elif action.action_id == "command_spell_transfer":result = action.command_spell_transfer()

        elif action.action_id == "chant":result = action.chant(decision_provider)

        elif action.action_id == "interrupt_casting":result = action.interrupt_casting()

        elif action.action_id == "release":result = action.release(decision_provider)

        elif action.action_id == "escape":result = action.escape()

        elif action.action_id == "surrender":result = action.surrender()

        elif action.action_id == "wish":result = action.wish()

        elif action.action_id == "join_travel_group":result = action.join_travel_group()
        elif action.action_id == "invite_carry":result = action.invite_carry(
            accepted=getattr(action, "confirmed", False),
        )
        elif action.action_id == "leave_carry":result = action.leave_carry()

        elif action.action_id == "join_battle":result = action.join_battle()

        elif action.action_id == "transfer_travel_leader":result = action.transfer_travel_leader()

        else: raise ValueError("未知的行动")

        if result:
            action.actor.modifier_manager.consume_event(
                "action_committed",
                {
                    "actor": action.actor,
                    "source": action,
                    "target": getattr(action, "target", None),
                    "action_id": action.action_id,
                    "event": action,
                    "tags": {"action"},
                },
            )

        if event_manager is not None:
            event_manager.emit(
                "action_resolved",
                actor=action.actor,
                source=action,
                target=getattr(action, "target", None),
                value=result if isinstance(result, (int, float)) else None,
                phase=getattr(action, "definition", {}).get(
                    "resolution_timing",
                    "action",
                ),
                battle=getattr(action.actor, "current_battle", None),
                position=getattr(action.actor, "position", None),
                payload={"action_id": action.action_id, "result": result},
                decision_provider=decision_provider,
            )
        return result

    
