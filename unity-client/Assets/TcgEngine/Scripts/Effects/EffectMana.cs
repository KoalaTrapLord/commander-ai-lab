using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect to gain/lose mana (player)
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/Mana", order = 10)]
    public class EffectMana : EffectData
    {
        public bool increase_value;
        public bool increase_max;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            if (increase_max)
            {
                target.mana_max += ability.value;
                target.mana_max = Mathf.Clamp(target.mana_max, 0, GameplayData.Get().mana_max);
            }
            
            if(increase_value)
            {
                target.mana += ability.value;
                target.mana = Mathf.Max(target.mana, 0);
            }
        }

    }
}