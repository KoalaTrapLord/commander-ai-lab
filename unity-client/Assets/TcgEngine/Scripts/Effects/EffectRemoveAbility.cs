using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect that removes an ability from a card
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/RemoveAbility", order = 10)]
    public class EffectRemoveAbility : EffectData
    {
        public AbilityData remove_ability;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            target.RemoveAbility(remove_ability);
        }
    }
}