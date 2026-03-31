using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using UnityEngine.EventSystems;

namespace TcgEngine.UI
{
    /// <summary>
    /// One of the squares in the history bar
    /// </summary>

    public class TurnHistoryLine : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
    {
        public HoverTargetUI hover;
        public Image card_img;

        private Card card;
        private float timer = 0f;
        private bool is_hover = false;

        private static List<TurnHistoryLine> line_list = new List<TurnHistoryLine>();

        void Awake()
        {
            line_list.Add(this);
        }

        void OnDestroy()
        {
            line_list.Add(this);
        }

        void Start()
        {
            gameObject.SetActive(false);
        }

        private void Update()
        {
            timer += Time.deltaTime;
        }

        public void SetLine(ActionHistory history)
        {
            Game gdata = GameClient.Get().GetGameData();
            Card acard = gdata.GetCard(history.card_uid);
            Card target = gdata.GetCard(history.target_uid);
            Player ptarget = gdata.GetPlayer(history.target_id);
            CardData icard = CardData.Get(history.card_id);
            CardData itarget = CardData.Get(target?.card_id);
            VariantData variant = acard.VariantData;
            AbilityData iability = AbilityData.Get(history.ability_id);
            card = acard;

            if (icard == null)
                return;

            if (history.type == GameAction.PlayCard)
            {
                string text = icard.title + " was played";
                SetLine(icard, variant, text);
            }

            if (history.type == GameAction.Move)
            {
                string text = icard.title + " moved";
                SetLine(icard, variant, text);
            }

            if (history.type == GameAction.Attack && itarget != null)
            {
                string text = icard.title + " attacked " + itarget.title;
                SetLine(icard, variant, text);
            }

            if (history.type == GameAction.AttackPlayer && ptarget != null)
            {
                string text = icard.title + " attacked " + ptarget.username;
                SetLine(icard, variant, text);
            }

            if (history.type == GameAction.CastAbility && iability != null)
            {
                if (iability.target == AbilityTarget.SelectTarget && itarget != null)
                {
                    string text = icard.title + " casted " + iability.GetTitle() + " on " + itarget.title;
                    SetLine(icard, variant, text);
                }
                else
                {
                    string text = icard.title + " casted " + iability.GetTitle();
                    SetLine(icard, variant, text);
                }
            }

            if (history.type == GameAction.SecretTriggered)
            {
                string text = icard.title + " was triggered";
                SetLine(icard, variant, text);
            }

        }

        public void SetLine(CardData icard, VariantData variant, string text)
        {
            card_img.sprite = icard.GetFullArt(variant);
            hover.text = text;
            gameObject.SetActive(true);
            timer = 0f;
        }

        public void Hide()
        {
            card = null;
            if (timer > 0.05f)
                gameObject.SetActive(false);
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            timer = 0f;
            is_hover = true;
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            timer = 0f;
            is_hover = false;
        }

        void OnDisable()
        {
            is_hover = false;
        }

        public static Card GetHoverCard()
        {
            foreach (TurnHistoryLine line in line_list)
            {
                if (line.card != null && line.is_hover)
                    return line.card;
            }
            return null;
        }
    }
}
