using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect that sets basic stats (hp/attack/mana) to a specific value
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/SetStat", order = 10)]
    public class EffectSetStat : EffectData
    {
        public EffectStatType type;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            if (type == EffectStatType.HP)
            {
                target.hp = ability.value;
            }

            if (type == EffectStatType.Mana)
            {
                target.mana = ability.value;
                target.mana = Mathf.Max(target.mana, 0);
            }
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            if (type == EffectStatType.Attack)
                target.attack = ability.value;
            if (type == EffectStatType.Mana)
                target.mana = ability.value;
            if (type == EffectStatType.HP)
            {
                target.hp = ability.value;
                target.damage = 0;
            }
        }

        public override void DoOngoingEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            if (type == EffectStatType.Attack)
                target.attack = ability.value;
            if (type == EffectStatType.HP)
                target.hp = ability.value;
            if (type == EffectStatType.Mana)
                target.mana = ability.value;
        }

    }
}