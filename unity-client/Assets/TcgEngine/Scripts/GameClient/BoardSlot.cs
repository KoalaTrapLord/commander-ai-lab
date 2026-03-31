using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using TcgEngine.Client;
using TcgEngine.UI;

namespace TcgEngine.Client
{
    /// <summary>
    /// Visual representation of a Slot.cs
    /// Will highlight when can be interacted with
    /// </summary>

    public class BoardSlot : BSlot
    {
        public BoardSlotType type;
        public int x;
        public int y;

        private static List<BoardSlot> slot_list = new List<BoardSlot>();

        protected override void Awake()
        {
            base.Awake();
            slot_list.Add(this);
        }

        protected override void OnDestroy()
        {
            base.OnDestroy();
            slot_list.Remove(this);
        }

        private void Start()
        {
            if (x < Slot.x_min || x > Slot.x_max || y < Slot.y_min || y > Slot.y_max)
                Debug.LogError("Board Slot X and Y value must be within the min and max set for those values, check Slot.cs script to change those min/max.");

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

            BoardCard bcard_selected = PlayerControls.Get().GetSelected();
            HandCard drag_card = HandCard.GetDrag();

            Game gdata = GameClient.Get().GetGameData();
            Player player = GameClient.Get().GetPlayer();
            Slot slot = GetSlot();
            Card dcard = drag_card?.GetCard();
            Card slot_card = gdata.GetSlotCard(GetSlot());
            bool your_turn = GameClient.Get().IsYourTurn();
            collide.enabled = slot_card == null; //Disable collider when a card is here

            //Find target opacity value
            target_alpha = 0f;
            if (your_turn && dcard != null && dcard.CardData.IsBoardCard() && gdata.CanPlayCard(dcard, slot))
            {
                target_alpha = 1f; //hightlight when dragging a character or artifact
            }

            if (your_turn && dcard != null && dcard.CardData.IsRequireTarget() && gdata.CanPlayCard(dcard, slot))
            {
                target_alpha = 1f; //Highlight when dragin a spell with target
            }

            if (gdata.selector == SelectorType.SelectTarget && player.player_id == gdata.selector_player_id)
            {
                Card caster = gdata.GetCard(gdata.selector_caster_uid);
                AbilityData ability = AbilityData.Get(gdata.selector_ability_id);
                if(ability != null && slot_card == null && ability.CanTarget(gdata, caster, slot))
                    target_alpha = 1f; //Highlight when selecting a target and slot are valid
                if (ability != null && slot_card != null && ability.CanTarget(gdata, caster, slot_card))
                    target_alpha = 1f; //Highlight when selecting a target and cards are valid
            }

            Card select_card = bcard_selected?.GetCard();
            bool can_do_move = your_turn && select_card != null && slot_card == null && gdata.CanMoveCard(select_card, slot);
            bool can_do_attack = your_turn && select_card != null && slot_card != null && gdata.CanAttackTarget(select_card, slot_card);

            if (can_do_attack || can_do_move)
            {
                target_alpha = 1f;
            }
        }

        //Find the actual slot coordinates of this board slot
        public override Slot GetSlot()
        {
            int p = 0;

            if (type == BoardSlotType.FlipX)
            {
                int pid = GameClient.Get().GetPlayerID();
                int px = x;
                if ((pid % 2) == 1)
                    px = Slot.x_max - x + Slot.x_min; //Flip X coordinate if not the first player
                return new Slot(px, y, p);
            }

            if (type == BoardSlotType.FlipY)
            {
                int pid = GameClient.Get().GetPlayerID();
                int py = y;
                if ((pid % 2) == 1)
                    py = Slot.y_max - y + Slot.y_min; //Flip Y coordinate if not the first player
                return new Slot(x, py, p);
            }

            if (type == BoardSlotType.PlayerSelf)
                p = GameClient.Get().GetPlayerID();
            if(type == BoardSlotType.PlayerOpponent)
                p = GameClient.Get().GetOpponentPlayerID();
           
            return new Slot(x, y, p);
        }

        //When clicking on the slot
        private void OnPointerClick(PointerEventData edata)
        {
            if (GameUI.IsOverUILayer("UI"))
                return;

            Game gdata = GameClient.Get().GetGameData();
            int player_id = GameClient.Get().GetPlayerID();

            if (gdata.selector == SelectorType.SelectTarget && player_id == gdata.selector_player_id)
            {
                Slot slot = GetSlot();
                Card slot_card = gdata.GetSlotCard(slot);
                if (slot_card == null)
                {
                    GameClient.Get().SelectSlot(slot);
                }
            }
        }

    }
}