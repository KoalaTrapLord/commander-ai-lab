using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect to transform a card into another card
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/Transform", order = 10)]
    public class EffectTransform : EffectData
    {
        public CardData transform_to;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            logic.TransformCard(target, transform_to);
        }
    }
}