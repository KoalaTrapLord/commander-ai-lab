using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Add/Reduce selected value
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/SelectedValue", order = 10)]
    public class EffectSelectedValue : EffectData
    {
        public EffectOperatorInt oper;
        public int value;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            logic.GameData.selected_value = AddOrSet(logic.GameData.selected_value, oper, value);
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            logic.GameData.selected_value = AddOrSet(logic.GameData.selected_value, oper, value);
        }

    }

}