using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using TcgEngine.UI;
using TcgEngine.FX;

namespace TcgEngine.Client
{
    /// <summary>
    /// Visual zone that can be attacked by opponent's card to damage the player HP
    /// </summary>

    public class BoardSlotPlayer : BSlot
    {
        public bool opponent;

        public float range_x = 3f;
        public float range_y = 1f;

        private static BoardSlotPlayer instance_self;
        private static BoardSlotPlayer instance_other;

        private static List<BoardSlotPlayer> zone_list = new List<BoardSlotPlayer>();

        protected override void Awake()
        {
            base.Awake();
            zone_list.Add(this);
            if (opponent)
                instance_other = this;
            else
                instance_self = this;
        }

        protected override void OnDestroy()
        {
            base.OnDestroy();
            zone_list.Remove(this);
        }

        private void Start()
        {
            GameClient.Get().onPlayerDamaged += OnPlayerDamaged;
            GameClient.Get().onAbilityStart += OnAbilityStart;
            GameClient.Get().onAbilityTargetPlayer += OnAbilityEffect;

            EventTrigger etrigger = GetComponent<EventTrigger>();
            EventTrigger.Entry entry0 = new EventTrigger.Entry();
            entry0.eventID = EventTriggerType.PointerClick;
            entry0.callback.AddListener((data) => { OnPointerClick((PointerEventData)data); });
            etrigger.triggers.Add(entry0);

        }

        protected override void Update()
        {
            base.Update();

            if (!GameClient.Get().IsReady())
                return;

            if (!opponent)
                return;

            //int player_id = opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
            BoardCard bcard_selected = PlayerControls.Get().GetSelected();
            HandCard drag_card = HandCard.GetDrag();
            bool your_turn = GameClient.Get().IsYourTurn();

            Game gdata = GameClient.Get().GetGameData();
            Player player = GameClient.Get().GetPlayer();
            Player oplayer = GameClient.Get().GetOpponentPlayer();

            target_alpha = 0f;
            Card select_card = bcard_selected?.GetCard();
            if (select_card != null)
            {
                bool can_do_attack = gdata.IsPlayerActionTurn(player) && select_card.CanAttack();
                bool can_be_attacked = gdata.CanAttackTarget(select_card, oplayer);

                if (can_do_attack && can_be_attacked)
                {
                    target_alpha = 1f;
                }
            }

            if (your_turn && drag_card != null && drag_card.CardData.IsRequireTargetSpell() && gdata.IsPlayTargetValid(drag_card.GetCard(), GetPlayer()))
            {
                target_alpha = 1f; //Highlight when dragin a spell with target
            }

            if (gdata.selector == SelectorType.SelectTarget && player.player_id == gdata.selector_player_id)
            {
                Card caster = gdata.GetCard(gdata.selector_caster_uid);
                AbilityData ability = AbilityData.Get(gdata.selector_ability_id);
                if (ability != null && ability.AreTargetConditionsMet(gdata, caster, GetPlayer()))
                    target_alpha = 1f; //Highlight when selecting a target and empty slots are valid
            }

        }

        private void OnAbilityStart(AbilityData iability, Card caster)
        {
            if (iability != null && caster != null)
            {
                int player_id = opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
                if (caster.CardData.type == CardType.Spell && caster.player_id == player_id)
                {
                    FXTool.DoFX(iability.caster_fx, transform.position);
                    AudioTool.Get().PlaySFX("fx", iability.cast_audio);
                }
            }
        }

        private void OnAbilityEffect(AbilityData iability, Card caster, Player target)
        {
            if (iability != null && caster != null && target != null)
            {
                int player_id = opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
                if (target.player_id == player_id)
                {
                    FXTool.DoFX(iability.target_fx, transform.position);
                    FXTool.DoProjectileFX(iability.projectile_fx, GetFXSource(caster), transform, iability.GetDamage());
                    AudioTool.Get().PlaySFX("fx", iability.target_audio);
                }
            }
        }

        private void OnPlayerDamaged(Player target, int damage)
        {
            if (GetPlayerID() == target.player_id && damage > 0)
            {
                DamageFX(transform, damage);
            }
        }

        private void DamageFX(Transform target, int value, float delay = 0.5f)
        {
            TimeTool.WaitFor(delay, () =>
            {
                GameObject fx = FXTool.DoFX(AssetData.Get().damage_fx, target.position);
                fx.GetComponent<DamageFX>().SetValue(value);
            });
        }

        private Transform GetFXSource(Card caster)
        {
            if (caster.CardData.IsBoardCard())
            {
                BoardCard bcard = BoardCard.Get(caster.uid);
                if (bcard != null)
                    return bcard.transform;
            }
            else
            {
                BoardSlotPlayer slot = BoardSlotPlayer.Get(caster.player_id);
                if (slot != null)
                    return slot.transform;
            }
            return null;
        }

        public void OnPointerClick(PointerEventData edata)
        {
            if (GameUI.IsUIOpened() || GameUI.IsOverUILayer("UI"))
                return;

            Game gdata = GameClient.Get().GetGameData();
            int player_id = GameClient.Get().GetPlayerID();
            if (gdata.selector == SelectorType.SelectTarget && player_id == gdata.selector_player_id)
            {
                GameClient.Get().SelectPlayer(GetPlayer());
            }
        }

        public int GetPlayerID()
        {
            return opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
        }

        public override Player GetPlayer()
        {
            return opponent ? GameClient.Get().GetOpponentPlayer() : GameClient.Get().GetPlayer();
        }

        public override Slot GetSlot()
        {
            return new Slot(GetPlayerID());
        }

        public static BoardSlotPlayer Get(bool opponent)
        {
            if(opponent)
                return instance_other;
            return instance_self;
        }

        public static BoardSlotPlayer Get(int player_id)
        {
            bool opponent = player_id != GameClient.Get().GetPlayerID();
            return Get(opponent);
        }
    }
}