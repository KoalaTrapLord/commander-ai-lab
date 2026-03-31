using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Check selected value for card cost
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/SelectedValue", order = 10)]
    public class ConditionSelectedValue : ConditionData
    {
        [Header("Selected Value is")]
        public ConditionOperatorInt oper;
        public int value;

        public override bool IsTriggerConditionMet(Game data, AbilityData ability, Card caster)
        {
            return CompareInt(data.selected_value, oper, value);
        }
    }
}