using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// SlotRange check each axis variable individualy for range between the caster and target
    /// If you want to check the travel distance instead (all at once) use SlotDist
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/SlotRange", order = 11)]
    public class ConditionSlotRange : ConditionData
    {
        [Header("Slot Range")]
        public int range_x = 1;
        public int range_y = 1;
        public int range_p = 0;
        
        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return IsTargetConditionMet(data, ability, caster, target.slot);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        { 
            Slot cslot = caster.slot;
            int dist_x = Mathf.Abs(cslot.x - target.x);
            int dist_y = Mathf.Abs(cslot.y - target.y);
            int dist_p = Mathf.Abs(cslot.p - target.p);
            return dist_x <= range_x && dist_y <= range_y && dist_p <= range_p;
        }
    }
}