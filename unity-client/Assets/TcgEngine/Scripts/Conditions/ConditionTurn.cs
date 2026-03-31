using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Checks if its your turn
    /// </summary>
    
    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/Turn", order = 10)]
    public class ConditionTurn : ConditionData
    {
        public ConditionOperatorBool oper;

        public override bool IsTriggerConditionMet(Game data, AbilityData ability, Card caster)
        {
            bool yourturn = caster.player_id == data.current_player;
            return CompareBool(yourturn, oper);
        }
    }
}