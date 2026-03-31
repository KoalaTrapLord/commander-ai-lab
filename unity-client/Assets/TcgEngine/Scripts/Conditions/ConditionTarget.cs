using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.AI;

namespace TcgEngine
{
    /// <summary>
    /// Condition that compares the target category of an ability to the actual target (card, player or slot)
    /// </summary>

    [CreateAssetMenu(fileName = "condition", menuName = "TcgEngine/Condition/Player", order = 10)]
    public class ConditionTarget : ConditionData
    {
        [Header("Target is of type")]
        public ConditionTargetType type;
        public ConditionOperatorBool oper;

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return CompareBool(type == ConditionTargetType.Card, oper); //Is Card
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Player target)
        {
            return CompareBool(type == ConditionTargetType.Player, oper); //Is Player
        }

        public override bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            return CompareBool(type == ConditionTargetType.Slot, oper); //Is Player
        }
    }

    public enum ConditionTargetType
    {
        None = 0,
        Card = 10,
        Player = 20,
        Slot = 30,
    }
}