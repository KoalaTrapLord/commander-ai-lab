using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;

namespace TcgEngine.Client
{
    /// <summary>
    /// Same as HandCard, but simpler version for the opponent's cards
    /// </summary>

    public class HandCardBack : MonoBehaviour
    {
        public Image card_sprite;

        private RectTransform rect;

        private static List<HandCardBack> card_list = new List<HandCardBack>();

        void Awake()
        {
            card_list.Add(this);
            rect = GetComponent<RectTransform>();
            SetCardback(null);
        }

        private void Start()
        {
            EventTrigger etrigger = GetComponent<EventTrigger>();
            EventTrigger.Entry entry0 = new EventTrigger.Entry();
            entry0.eventID = EventTriggerType.PointerDown;
            entry0.callback.AddListener((data) => { OnPointerDown((PointerEventData)data); });
            etrigger.triggers.Add(entry0);
        }

        private void OnDestroy()
        {
            card_list.Remove(this);
        }

        public void SetCardback(CardbackData cb)
        {
            if (cb != null && cb.cardback != null)
                card_sprite.sprite = cb.cardback;
        }

        private void OnPointerDown(PointerEventData edata)
        {
            BoardSlotPlayer bslot = BoardSlotPlayer.Get(true);
            if (bslot != null)
            {
                bslot.OnPointerClick(edata);
            }
        }

        public RectTransform GetRect()
        {
            if (rect == null)
                return GetComponent<RectTransform>();
            return rect;
        }

    }
}
