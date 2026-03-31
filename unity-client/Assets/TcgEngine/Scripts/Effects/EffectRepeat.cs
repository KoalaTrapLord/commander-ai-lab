using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Repeat an ability X times
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/Repeat", order = 10)]
    public class EffectRepeat : EffectData
    {
        public AbilityData ability;
        public EffectRepeatType type;

        public override void DoEffect(GameLogic logic, AbilityData iability, Card caster)
        {
            int count = GetRepeatCount(logic.GameData, iability);
            for (int i = 0; i < count; i++)
            {
                Card triggerer = logic.GameData.GetCard(logic.GameData.ability_triggerer);
                logic.TriggerAbilityDelayed(this.ability, caster, triggerer);
            }
        }

        public override void DoEffect(GameLogic logic, AbilityData iability, Card caster, Player target)
        {
            int count = GetRepeatCount(logic.GameData, iability);
            for (int i = 0; i < count; i++)
            {
                Card triggerer = logic.GameData.GetCard(logic.GameData.ability_triggerer);
                logic.TriggerAbilityDelayed(this.ability, caster, triggerer);
            }
        }

        public override void DoEffect(GameLogic logic, AbilityData iability, Card caster, Card target)
        {
            int count = GetRepeatCount(logic.GameData, iability);
            for (int i = 0; i < count; i++)
            {
                Card triggerer = logic.GameData.GetCard(logic.GameData.ability_triggerer);
                logic.TriggerAbilityDelayed(this.ability, caster, triggerer);
            }
        }

        public int GetRepeatCount(Game game, AbilityData iability)
        {
            if (type == EffectRepeatType.SelectedValue)
                return game.selected_value;
            if (type == EffectRepeatType.FixedValue)
                return iability.value;
            return 0;
        }
    }


    public enum EffectRepeatType
    {
        FixedValue,
        SelectedValue
    }
}