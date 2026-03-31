using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine.Client
{
    /// <summary>
    /// Same as HandCardArea but for the opponents hand
    /// Simpler version with display only (no draging of card)
    /// </summary>

    public class OpponentHand : MonoBehaviour
    {
        public GameObject card_prefab;
        public RectTransform card_area;
        public float card_spacing = 100f;
        public float card_angle = 10f;
        public float card_offset_y = 10f;

        private List<HandCardBack> cards = new List<HandCardBack>();

        void Start()
        {

        }

        void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            Game gdata = GameClient.Get().GetGameData();
            Player player = gdata.GetPlayer(GameClient.Get().GetOpponentPlayerID());

            if (cards.Count < player.cards_hand.Count)
            {
                GameObject new_card = Instantiate(card_prefab, card_area);
                HandCardBack hand_card = new_card.GetComponent<HandCardBack>();
                CardbackData cbdata = CardbackData.Get(player.cardback);
                hand_card.SetCardback(cbdata);
                RectTransform card_rect = new_card.GetComponent<RectTransform>();
                card_rect.anchoredPosition = new Vector2(0f, 100f);
                cards.Add(hand_card);
            }

            if (cards.Count > player.cards_hand.Count)
            {
                HandCardBack card = cards[cards.Count - 1];
                cards.RemoveAt(cards.Count - 1);
                Destroy(card.gameObject);
            }

            int nb_cards = Mathf.Min(cards.Count, player.cards_hand.Count);

            for (int i = 0; i < nb_cards; i++)
            {
                HandCardBack card = cards[i];
                RectTransform crect = card.GetRect();
                float half = nb_cards / 2f;
                Vector3 tpos = new Vector3((i - half) * card_spacing, (i - half) * (i - half) * card_offset_y);
                float tangle = (i - half) * card_angle;
                crect.anchoredPosition = Vector3.Lerp(crect.anchoredPosition, tpos, 4f * Time.deltaTime);
                card.transform.localRotation = Quaternion.Slerp(card.transform.localRotation, Quaternion.Euler(0f, 0f, tangle), 4f * Time.deltaTime);
            }

        }
    }
}