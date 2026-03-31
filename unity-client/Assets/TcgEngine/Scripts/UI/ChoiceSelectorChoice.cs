using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// One choice in the choice selector
    /// Its a button you can click
    /// </summary>

    public class ChoiceSelectorChoice : MonoBehaviour
    {
        public Text title;
        public Text subtitle;
        public Image highlight;

        public UnityAction<int> onClick;

        private Button button;
        private int choice;
        private bool focus = false;

        private void Awake()
        {
            button = GetComponent<Button>();
            button.onClick.AddListener(OnClick);
        }

        private void Update()
        {
            if (highlight != null)
                highlight.enabled = focus;
        }

        public void SetChoice(int choice, AbilityData ability)
        {
            this.choice = choice;
            this.title.text = ability.title;
            this.subtitle.text = ability.desc;
            button.interactable = true;
            gameObject.SetActive(true);

            if (ability.mana_cost > 0)
                this.title.text += " (" + ability.mana_cost + ")";
        }

        public void SetInteractable(bool interact)
        {
            button.interactable = interact;
        }

        public void Hide()
        {
            gameObject.SetActive(false);
        }

        public void OnClick()
        {
            onClick?.Invoke(choice);
        }

        public void MouseEnter()
        {
            if (button.interactable)
                focus = true;
        }

        public void MouseExit()
        {
            focus = false;
        }
    }
}
