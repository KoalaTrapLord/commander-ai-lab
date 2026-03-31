using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Add this to an ability to prevent it from being cast more than once per turn
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/OncePerTurn", order = 10)]
    public class ConditionOnce : ConditionData
    {
        public override bool IsTriggerConditionMet(Game data, AbilityData ability, Card caster)
        {
            return !data.ability_played.Contains(ability.id);
        }

    }
}