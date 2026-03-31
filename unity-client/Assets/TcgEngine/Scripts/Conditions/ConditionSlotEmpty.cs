using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Checks if a slot contains a card or not
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/SlotEmpty", order = 11)]
    public class ConditionSlotEmpty : ConditionData
    {
        [Header("Slot Is Empty")]
        public ConditionOperatorBool oper;

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return CompareBool(false, oper); //Target is not empty slot
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Player target)
        {
            return CompareBool(false, oper); //Target is not empty slot
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        { 
            Card slot_card = data.GetSlotCard(target);
            return CompareBool(slot_card == null, oper);
        }
    }
}