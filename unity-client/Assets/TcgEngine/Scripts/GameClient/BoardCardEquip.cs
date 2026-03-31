using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using TcgEngine.UI;

namespace TcgEngine.Client
{

    public class BoardCardEquip : MonoBehaviour
    {
        public Image equip_sprite;
        public Image equip_glow;
        public Text equip_hp;

        public Color glow_ally;
        public Color glow_enemy;

        private Canvas canvas;
        private RectTransform rect;

        private Card equip;
        private bool focus;
        private float target_alpha = 0f;

        void Awake()
        {
            canvas = GetComponentInParent<Canvas>();
            rect = GetComponent<RectTransform>();
        }

        private void Update()
        {
            if (equip != null)
            {
                target_alpha = focus ? 1f : 0f;
                focus = GameUI.IsOverRectTransform(canvas, rect);
            }
            else
            {
                target_alpha = 0f;
                focus = false;
            }

            if (equip_glow != null)
            {
                int player_id = GameClient.Get().GetPlayerID();
                Color ccolor = player_id == equip.player_id ? glow_ally : glow_enemy;
                float calpha = Mathf.MoveTowards(equip_glow.color.a, target_alpha * ccolor.a, 4f * Time.deltaTime);
                equip_glow.color = new Color(ccolor.r, ccolor.g, ccolor.b, calpha);
            }
        }

        public void SetEquip(Card equip)
        {
            if (equip != null)
            {
                this.equip = equip;
                equip_sprite.sprite = equip.CardData.GetBoardArt(equip.VariantData);
                equip_hp.text = equip.GetHP().ToString();

                if (!gameObject.activeSelf)
                    gameObject.SetActive(true);
            }
            else
            {
                Hide();
            }
        }

        public void Hide()
        {
            this.equip = null;
            focus = false;
            if (gameObject.activeSelf)
                gameObject.SetActive(false);
        }

        public bool IsFocus()
        {
            return equip != null && focus;
        }

        public Card GetCard()
        {
            return equip;
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            focus = true;
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            focus = false;
        }

        void OnDisable()
        {
            focus = false;
        }
    }
}
