using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect to redirect an attack (usually triggered with OnBeforeAttack or OnBeforeDefend)
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/AttackRedirect", order = 10)]
    public class EffectAttackRedirect : EffectData
    {
        public EffectAttackerType attacker_type;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            Card attacker = GetAttacker(logic.GetGameData(), caster);
            if (attacker != null)
            {
                logic.RedirectAttack(attacker, target);
            }
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            Card attacker = GetAttacker(logic.GetGameData(), caster);
            if (attacker != null)
            {
                logic.RedirectAttack(attacker, target);
            }
        }

        public Card GetAttacker(Game gdata, Card caster)
        {
            if (attacker_type == EffectAttackerType.Self)
                return caster;
            if (attacker_type == EffectAttackerType.AbilityTriggerer)
                return gdata.GetCard(gdata.ability_triggerer);
            if (attacker_type == EffectAttackerType.LastPlayed)
                return gdata.GetCard(gdata.last_played);
            if (attacker_type == EffectAttackerType.LastTargeted)
                return gdata.GetCard(gdata.last_target);
            return null;
        }
    }
}