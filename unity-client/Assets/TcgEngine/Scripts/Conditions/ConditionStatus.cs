using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    //Checks if a player or card has a status effect
    
    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/CardStatus", order = 10)]
    public class ConditionStatus : ConditionData
    {
        [Header("Card has status")]
        public StatusType has_status;
        public int value = 0;
        public ConditionOperatorBool oper;

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            bool hstatus = target.HasStatus(has_status) && target.GetStatusValue(has_status) >= value;
            return CompareBool(hstatus, oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Player target)
        {
            bool hstatus = target.HasStatus(has_status) && target.GetStatusValue(has_status) >= value;
            return CompareBool(hstatus, oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            Card card = data.GetSlotCard(target);
            if (card != null)
                return IsTargetConditionMet(data, ability, caster, card);
            return false;
        }
    }
}