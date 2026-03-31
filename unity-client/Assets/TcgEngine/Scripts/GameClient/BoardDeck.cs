using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using TcgEngine.UI;

namespace TcgEngine.Client
{
    /// <summary>
    /// Represents the visual deck on the board
    /// Will show number of cards in deck/discard when hovering
    /// </summary>
    
    public class BoardDeck : MonoBehaviour
    {
        public bool opponent;
        public UIPanel hover_panel;
        public SpriteRenderer deck_render;
        public Text deck_value;
        public Text discard_value;

        private bool hover = false;
        
        void Start()
        {
            if (GameTool.IsMobile())
            {
                hover_panel?.SetVisible(true);
            }

            EventTrigger etrigger = GetComponent<EventTrigger>();

            EventTrigger.Entry entry0 = new EventTrigger.Entry();
            entry0.eventID = EventTriggerType.PointerClick;
            entry0.callback.AddListener((data) => { OnPointerClick((PointerEventData)data); });
            etrigger.triggers.Add(entry0);

            EventTrigger.Entry entry1 = new EventTrigger.Entry();
            entry1.eventID = EventTriggerType.PointerEnter;
            entry1.callback.AddListener((data) => { OnPointerEnter((PointerEventData)data); });
            etrigger.triggers.Add(entry1);

            EventTrigger.Entry entry2 = new EventTrigger.Entry();
            entry2.eventID = EventTriggerType.PointerExit;
            entry2.callback.AddListener((data) => { OnPointerExit((PointerEventData)data); });
            etrigger.triggers.Add(entry2);
        }

        void Update()
        {
            Refresh();
        }

        private void Refresh()
        {
            if (!GameClient.Get().IsReady())
                return;

            Player player = opponent ? GameClient.Get().GetOpponentPlayer() : GameClient.Get().GetPlayer();
            if (player == null)
                return;

            CardbackData cb = CardbackData.Get(player.cardback);
            if (deck_render != null && cb != null)
                deck_render.sprite = cb.deck;

            if (deck_value != null)
                deck_value.text = player.cards_deck.Count.ToString();
            if (discard_value != null)
                discard_value.text = player.cards_discard.Count.ToString();
        }

        public void ShowDeckCards()
        {
            Player player = GameClient.Get().GetPlayer();
            CardSelector.Get().Show(player.cards_deck, "DECK");
        }

        public void ShowDiscardCards()
        {
            Player player = opponent ? GameClient.Get().GetOpponentPlayer() : GameClient.Get().GetPlayer();
            CardSelector.Get().Show(player.cards_discard, "DISCARD");
        }

        private void ShowHover(bool hover)
        {
            if(!GameTool.IsMobile())
                hover_panel?.SetVisible(hover);
        }

        private void OnPointerEnter(PointerEventData edata)
        {
            hover = true;
            ShowHover(hover);
            Refresh();
        }

        private void OnPointerExit(PointerEventData edata)
        {
            hover = false;
            ShowHover(hover);
        }

        private void OnPointerClick(PointerEventData edata)
        {
            if (!opponent && edata.button == PointerEventData.InputButton.Left)
            {
                ShowDeckCards(); //Cannot see opponent deck
            }
            if (edata.button == PointerEventData.InputButton.Right)
            {
                ShowDiscardCards(); //Cant see both player discard
            }
        }

        private void OnDisable()
        {
            hover = false;
            ShowHover(hover);
        }
    }
}
