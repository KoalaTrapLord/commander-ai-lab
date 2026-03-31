using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Condition that check the owner of the target match the owner of the caster
    /// </summary>
    
    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/CardOwner", order = 10)]
    public class ConditionOwner : ConditionData
    {
        [Header("Target owner is caster owner")]
        public ConditionOperatorBool oper;

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            bool same_owner = caster.player_id == target.player_id;
            return CompareBool(same_owner, oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Player target)
        {
            bool same_owner = caster.player_id == target.player_id;
            return CompareBool(same_owner, oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            bool same_owner = Slot.GetP(caster.player_id) == target.p;
            return CompareBool(same_owner, oper);
        }
    }
}