using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// SlotDist is the travel distance from the caster to the target
    /// Unlike SlotRange which is just checking each X,Y,P separately
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/SlotDist", order = 11)]
    public class ConditionSlotDist : ConditionData
    {
        [Header("Slot Distance")]
        public int distance = 1;
        public bool diagonals;
        
        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return IsTargetConditionMet(data, ability, caster, target.slot);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            Slot cslot = caster.slot;
            if (diagonals)
                return cslot.IsInDistance(target, distance);
            return cslot.IsInDistanceStraight(target, distance);
        }
    }
}