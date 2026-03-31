using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    public class CardMulligan : MonoBehaviour
    {
        public CardUI card_ui;
        public Image x_img;

        private Card card;

        public UnityAction<CardMulligan> onClick;

        private void Awake()
        {
            if (x_img != null)
                x_img.enabled = false;

            card_ui.onClick += OnClick;
        }

        public void SetCard(Card card)
        {
            this.card = card;
            card_ui.SetCard(card.CardData, card.VariantData);
            gameObject.SetActive(true);
        }

        public void SetSelected(bool discard)
        {
            if (x_img != null)
                x_img.enabled = discard;
        }

        public void Hide()
        {
            gameObject.SetActive(false);
        }

        public bool IsSelected()
        {
            if (x_img != null)
                return x_img.enabled;
            return false;
        }

        public Card GetCard()
        {
            return card;
        }

        private void OnClick(CardUI card_ui)
        {
            onClick?.Invoke(this);
        }

    }
}