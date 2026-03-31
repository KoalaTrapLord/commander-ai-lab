using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine
{
    //Effect to Summon an entirely new card (not in anyones deck)
    //And places it on the board (if target slot) or hand (if target player)
    //Unlike EffectCreate, this effect targets where the card goes, and the carddata is selected on the effect

    [CreateAssetMenu(fileName = "effect", menuName = "TcgEngine/Effect/Summon", order = 10)]
    public class EffectSummon : EffectData
    {
        public CardData summon;

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Player target)
        {
            logic.SummonCardHand(target, summon, caster.VariantData); //Summon in hand instead of board when target a player
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Card target)
        {
            Player player = logic.GameData.GetPlayer(caster.player_id);
            logic.SummonCard(player, summon, caster.VariantData, target.slot); //Assumes the target has just been killed, so the slot is empty
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, Slot target)
        {
            Player player = logic.GameData.GetPlayer(caster.player_id);
            logic.SummonCard(player, summon, caster.VariantData, target);
        }

        public override void DoEffect(GameLogic logic, AbilityData ability, Card caster, CardData target)
        {
            Player player = logic.GameData.GetPlayer(caster.player_id);
            logic.SummonCardHand(player, target, caster.VariantData);   //Summon in hand instead of board when target a carddata
        }
    }
}