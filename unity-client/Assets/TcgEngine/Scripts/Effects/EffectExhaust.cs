using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect that exhaust or unexhaust a card (means it can no longer perform actions or will be able to perform another action)
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/Exhaust", order = 10)]
    public class EffectExhaust : EffectData
    {
        public bool exhausted;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            target.exhausted = exhausted;
        }

    }
}