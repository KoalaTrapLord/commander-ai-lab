using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Effect to make a card attack a target
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/Attack", order = 10)]
    public class EffectAttack : EffectData
    {
        public EffectAttackerType attacker_type;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            Card attacker = GetAttacker(logic.GetGameData(), caster);
            if (attacker != null)
            {
                logic.AttackPlayer(attacker, target, true);
            }
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            Card attack = GetAttacker(logic.GetGameData(), caster);
            if (attack != null)
            {
                logic.AttackTarget(attack, target, true);
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

    public enum EffectAttackerType
    {
        Self = 1,                  
        AbilityTriggerer = 25, 
        LastPlayed = 70,  
        LastTargeted = 72, 
    }
}