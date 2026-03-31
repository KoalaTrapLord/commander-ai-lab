using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// SlotValue compare each slot x and y to a specific value, like slot.x >=3 and slot.y < 5
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/SlotValue", order = 11)]
    public class ConditionSlotValue : ConditionData
    {
        [Header("Slot Value")]
        public ConditionOperatorInt oper_x;
        public int value_x = 0;

        public ConditionOperatorInt oper_y;
        public int value_y = 0;
        
        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return IsTargetConditionMet(data, ability, caster, target.slot);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            bool valid_x = CompareInt(target.x, oper_x, value_x);
            bool valid_y = CompareInt(target.y, oper_y, value_y);
            return valid_x && valid_y;
        }
    }
}