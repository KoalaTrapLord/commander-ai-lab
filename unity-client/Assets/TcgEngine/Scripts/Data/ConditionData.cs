using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Base class for all ability conditions, override the IsConditionMet function
    /// </summary>

    public class ConditionData : ScriptableObject
    {
        public virtual bool IsTriggerConditionMet(Game data, AbilityData ability, Card caster)
        {
            return true; //Override this, applies to any target, always checked
        }

        public virtual bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Card target)
        {
            return true; //Override this, condition targeting card
        }

        public virtual bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Player target)
        {
            return true; //Override this, condition targeting player
        }

        public virtual bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, Slot target)
        {
            return true; //Override this, condition targeting slot
        }

        public virtual bool IsTargetConditionMet(Game data, AbilityData ability, Card caster, CardData target)
        {
            return true; //Override this, for effects that create new cards
        }

        public bool CompareBool(bool condition, ConditionOperatorBool oper)
        {
            if (oper == ConditionOperatorBool.IsFalse)
                return !condition;
            return condition;
        }

        public bool CompareInt(int ival1, ConditionOperatorInt oper, int ival2)
        {
            if (oper == ConditionOperatorInt.Equal)
            {
                return ival1 == ival2;
            }
            if (oper == ConditionOperatorInt.NotEqual)
            {
                return ival1 != ival2;
            }
            if (oper == ConditionOperatorInt.GreaterEqual)
            {
                return ival1 >= ival2;
            }
            if (oper == ConditionOperatorInt.LessEqual)
            {
                return ival1 <= ival2;
            }
            if (oper == ConditionOperatorInt.Greater)
            {
                return ival1 > ival2;
            }
            if (oper == ConditionOperatorInt.Less)
            {
                return ival1 < ival2; ;
            }
            return false;
        }
    }

    public enum ConditionOperatorInt
    {
        Equal,
        NotEqual,
        GreaterEqual,
        LessEqual,
        Greater,
        Less,
    }

    public enum ConditionOperatorBool
    {
        IsTrue,
        IsFalse,
    }
}