using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine.UI
{

    public class MulliganSelector : SelectorPanel
    {
        public CardMulligan[] cards;

        private static MulliganSelector instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;

            foreach (CardMulligan card in cards)
            {
                card.onClick += OnClickCard;
            }
        }

        private void RefreshMulligan()
        {
            Player player = GameClient.Get().GetPlayer();

            int index = 0;
            foreach (Card card in player.cards_hand)
            {
                string bonus_id = GameplayData.Get().second_bonus != null ? GameplayData.Get().second_bonus.id : "";
                if (index < cards.Length && card.card_id != bonus_id)
                {
                    CardMulligan card_ui = cards[index];
                    card_ui.SetCard(card);
                    index++;
                }
            }
        }

        private void OnClickCard(CardMulligan card_ui)
        {
            card_ui.SetSelected(!card_ui.IsSelected());
        }

        public void OnClickOK()
        {
            List<string> selected_cards = new List<string>();

            foreach (CardMulligan acard in cards)
            {
                if (acard.IsSelected())
                    selected_cards.Add(acard.GetCard().uid);
            }

            GameClient.Get().Mulligan(selected_cards.ToArray());
            Hide();
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshMulligan();
        }

        public override bool ShouldShow()
        {
            Game gdata = GameClient.Get().GetGameData();
            Player player = GameClient.Get().GetPlayer();
            return gdata.IsPlayerMulliganTurn(player);
        }

        public static MulliganSelector Get()
        {
            return instance;
        }
    }
}