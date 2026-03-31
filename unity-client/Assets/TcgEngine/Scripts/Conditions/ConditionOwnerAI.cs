using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Condition that is checked only by the AI. 
    /// Prevents the AI from targeting itself with bad spells even though you want to give real players the flexibility to do it
    /// </summary>
    
    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/CardOwnerAI", order = 10)]
    public class ConditionOwnerAI : ConditionData
    {
        [Header("AI Only: Target owner is caster owner")]
        public ConditionOperatorBool oper;

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            if (!IsAIPlayer(data, caster))
                return true; //Condition always true for human players

            bool same_owner = caster.player_id == target.player_id;
            return CompareBool(same_owner, oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Player target)
        {
            if (!IsAIPlayer(data, caster))
                return true; //Condition always true for human players

            bool same_owner = caster.player_id == target.player_id;
            return CompareBool(same_owner, oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            if (!IsAIPlayer(data, caster))
                return true; //Condition always true for human players

            bool same_owner = Slot.GetP(caster.player_id) == target.p;
            return CompareBool(same_owner, oper);
        }

        private bool IsAIPlayer(Game data, Card caster)
        {
            Player player = data.GetPlayer(caster.player_id);
            return player.is_ai;
        }
    }
}