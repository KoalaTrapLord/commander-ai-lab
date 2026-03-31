using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;

namespace TcgEngine.UI
{

    public class SecretIconUI : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
    {
        private Card card = null;
        private bool is_hover = false;


        private static List<SecretIconUI> icon_list = new List<SecretIconUI>();

        void Awake()
        {
            icon_list.Add(this);
        }

        void OnDestroy()
        {
            icon_list.Remove(this);
        }

        public void SetCard(Card card)
        {
            this.card = card;
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            is_hover = true;
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            is_hover = false;
        }

        void OnDisable()
        {
            is_hover = false;
        }

        public Card GetCard()
        {
            return card;
        }

        public static Card GetHoverCard()
        {
            foreach (SecretIconUI line in icon_list)
            {
                if (line.card != null && line.is_hover)
                    return line.card;
            }
            return null;
        }

    }
}
