using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    /// <summary>
    /// Ability button on a BoardCard, let you activate abilities
    /// </summary>

    public class AbilityButton : MonoBehaviour
    {
        public Text text;
        public Image focus_highlight;

        private Card card;
        private AbilityData iability;

        private CanvasGroup canvas_group;
        private float target_alpha = 0f;
        private bool focus = false;
        private bool nextfocus = false;
        private bool interactable = false;

        private static List<AbilityButton> button_list = new List<AbilityButton>();

        void Awake()
        {
            button_list.Add(this);
            canvas_group = GetComponent<CanvasGroup>();
            canvas_group.alpha = 0f;
            if (focus_highlight != null)
                focus_highlight.enabled = false;
        }

        private void OnDestroy()
        {
            button_list.Remove(this);
        }

        void Update()
        {
            canvas_group.alpha = Mathf.MoveTowards(canvas_group.alpha, target_alpha, 5f * Time.deltaTime);
            focus = nextfocus;

            if (focus_highlight != null && IsVisible())
                focus_highlight.enabled = focus && interactable;
        }

        public void SetAbility(Card card, AbilityData iability)
        {
            this.card = card;
            this.iability = iability;
            text.text = iability.title;
            if (this.iability.mana_cost > 0)
                text.text += " (" + this.iability.mana_cost + ")";
            canvas_group.interactable = true;
            canvas_group.blocksRaycasts = true;
            target_alpha = 1f;
        }

        public void SetInteractable(bool interact)
        {
            interactable = interact;
        }

        public void Hide()
        {
            if (canvas_group == null)
                canvas_group = GetComponent<CanvasGroup>();

            this.card = null;
            this.iability = null;
            canvas_group.interactable = false;
            canvas_group.blocksRaycasts = false;
            target_alpha = 0f;
        }

        public void OnClick()
        {
            if (card != null && iability != null)
            {
                if (!Tutorial.Get().CanDo(TutoEndTrigger.CastAbility, card))
                    return;

                GameClient.Get().CastAbility(card, iability);
                PlayerControls.Get().UnselectAll();
            }
        }

        public AbilityData GetAbility()
        {
            return iability;
        }

        public bool IsVisible()
        {
            return canvas_group.alpha > 0.5f;
        }

        public bool IsInteractable()
        {
            return interactable && IsVisible();
        }

        public void MouseEnter()
        {
            focus = true;
            nextfocus = true;
        }

        public void MouseExit()
        {
            nextfocus = false; //Keep it focused 1 more frame to work on mobile
        }

        public static AbilityButton GetFocus(Vector3 pos, float range = 999f)
        {
            AbilityButton nearest = null;
            float min_dist = range;
            foreach (AbilityButton button in button_list)
            {
                float dist = (button.transform.position - pos).magnitude;
                if (button.focus && button.IsVisible() && dist < min_dist)
                {
                    min_dist = dist;
                    nearest = button;
                }
            }
            return nearest;
        }

        public static AbilityButton GetNearest(Vector3 pos, float range = 999f)
        {
            AbilityButton nearest = null;
            float min_dist = range;
            foreach (AbilityButton button in button_list)
            {
                float dist = (button.transform.position - pos).magnitude;
                if (dist < min_dist)
                {
                    min_dist = dist;
                    nearest = button;
                }
            }
            return nearest;
        }

    }
}
