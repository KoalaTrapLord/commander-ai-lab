using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    /// <summary>
    /// Change owner of target card to the owner of the caster (or the opponent player)
    /// </summary>

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/ChangeOwner", order = 10)]
    public class EffectChangeOwner : EffectData
    {
        public bool owner_opponent; //Change to self or opponent?

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            Game game = logic.GetGameData();
            Player tplayer = owner_opponent ? game.GetOpponentPlayer(caster.player_id) : game.GetPlayer(caster.player_id);
            logic.ChangeOwner(target, tplayer);
        }
    }
}