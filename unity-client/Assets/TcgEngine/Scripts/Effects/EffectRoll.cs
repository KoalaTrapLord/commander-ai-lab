using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Roll a dice, result is stored in logic.GameData.rolled_value
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/RollDice", order = 10)]
    public class EffectRoll : EffectData
    {
        public int dice = 6;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            logic.RollRandomValue(dice);
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            logic.RollRandomValue(dice);
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Slot target)
        {
            logic.RollRandomValue(dice);
        }
    }
}