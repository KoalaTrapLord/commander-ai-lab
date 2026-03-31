using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Condition that check if the CardData is a valid deckbuilding card (not a summon token)
    /// </summary>
    
    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/CardDeckbuilding", order = 10)]
    public class ConditionDeckbuilding : ConditionData
    {
        [Header("Card is Deckbuilding")]
        public ConditionOperatorBool oper;

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return CompareBool(target.CardData.IsDeckbuilding(), oper);
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, CardData target)
        {
            return CompareBool(target.IsDeckbuilding(), oper);
        }
    }
}