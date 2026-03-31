using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// In the game scene, the CardPreviewUI is what shows the card in big with extra info when hovering a card
    /// </summary>

    public class CardPreviewUI : MonoBehaviour
    {
        public UIPanel ui_panel;
        public CardUI card_ui;
        public Text desc;
        public float hover_delay_board = 0.7f;
        public float hover_delay_hand = 0.4f;
        public float hover_delay_mobile = 0.1f;

        public RectTransform[] side_rows;
        public StatusLine[] status_lines;

        private float preview_timer = 0f;
        private Vector2[] start_pos;

        private void Start()
        {
            start_pos = new Vector2[side_rows.Length];
            for (int i = 0; i < side_rows.Length; i++)
            {
                start_pos[i] = side_rows[i].anchoredPosition;
            }
        }

        void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            foreach (StatusLine line in status_lines)
                line.Hide();

            Card pcard = GetHoveredCard();
            float delay = GetHoverDelay();

            bool hover_only = !MouseInput.IsLeftHold() && !HandCardArea.Get().IsDragging();
            bool should_show_preview = hover_only && pcard != null && !GameUI.IsUIOpened();

            if (should_show_preview)
                preview_timer += Time.deltaTime;
            else
                preview_timer = 0f;

            bool show_preview = should_show_preview && preview_timer >= delay;
            ui_panel.SetVisible(show_preview);

            if (show_preview)
            {
                CardData icard = pcard.CardData;
                card_ui.SetCard(icard, pcard.VariantData);

                string cdesc = icard.GetDesc();
                string adesc = icard.GetAbilitiesDesc();
                if (!string.IsNullOrWhiteSpace(cdesc))
                    this.desc.text = cdesc + "\n\n" + adesc;
                else
                    this.desc.text = adesc;

                UpdateAbilities(pcard);
            }

        }

        private void UpdateAbilities(Card pcard)
        {
            //Abilities
            int index = 0;
            foreach (AbilityData ability in pcard.GetAbilities())
            {
                if (index < status_lines.Length)
                {
                    //Dont display default ability (GetAbilitiesDesc does that already)
                    if (!pcard.CardData.HasAbility(ability) && !string.IsNullOrWhiteSpace(ability.desc))
                    {
                        status_lines[index].SetLine(pcard.CardData, ability);
                        index++;
                    }
                }
            }

            //Status
            foreach (CardStatus status in pcard.GetAllStatus())
            {
                if (index < status_lines.Length)
                {
                    StatusData istatus = StatusData.Get(status.type);
                    if (istatus != null && !string.IsNullOrWhiteSpace(istatus.desc))
                    {
                        int ival = Mathf.Max(status.value, Mathf.CeilToInt(status.duration / 2f));
                        status_lines[index].SetLine(istatus, ival);
                        index++;
                    }
                }
            }
        }

        private Card GetHoveredCard()
        {
            PlayerControls controls = PlayerControls.Get();
            HandCard hcard = HandCard.GetFocus();
            BoardCard bcard = BoardCard.GetFocus();
            HeroUI hero_ui = HeroUI.GetFocus();
            Card histcard = TurnHistoryLine.GetHoverCard();
            Card secret_card = SecretIconUI.GetHoverCard();

            Card pcard = hcard != null ? hcard?.GetCard() : bcard?.GetFocusCard();
            if (pcard == null)
                pcard = histcard;
            if (pcard == null)
                pcard = secret_card;
            if (pcard == null)
                pcard = hero_ui?.GetCard();

            return pcard;
        }

        private float GetHoverDelay()
        {
            HandCard hcard = HandCard.GetFocus();
            float delay = hcard != null ? hover_delay_hand : hover_delay_board;
            if (GameTool.IsMobile())
                delay = hover_delay_mobile;
            return delay;
        }
    }
}
