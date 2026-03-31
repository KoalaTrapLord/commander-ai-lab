using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    [System.Serializable]
    public class OptionInt
    {
        public int value;
        public string title;
    }

    /// <summary>
    /// Option selector is a UI element with 2 arrows (left/right) to select an option among preset values
    /// This one let you select a int
    /// </summary>

    public class OptionSelectorInt : MonoBehaviour
    {
        [Header("Options")]
        public OptionInt[] options;

        [Header("Display")]
        public Text select_text;

        public UnityAction onChange;

        private int position = 0;
        private bool is_locked = false;

        void Start()
        {
            SetIndex(0);
        }

        void Update()
        {

        }

        private void AfterChangeOption()
        {
            if (select_text != null)
                select_text.text = GetSelectedTitle();
            onChange?.Invoke();
        }

        public void OnClickLeft()
        {
            if (is_locked)
                return;

            position = (position + options.Length - 1) % options.Length;
            AfterChangeOption();
        }

        public void OnClickRight()
        {
            if (is_locked)
                return;

            position = (position + options.Length + 1) % options.Length;
            AfterChangeOption();
        }

        public void SetIndex(int index)
        {
            position = index;
            if (select_text != null)
                select_text.text = GetSelectedTitle();
        }

        public void SetValue(int value)
        {
            for (int i = 0; i < options.Length; i++)
            {
                if (options[i].value == value)
                    position = i;
            }

            if (select_text != null)
                select_text.text = GetSelectedTitle();
        }

        public void SetLocked(bool locked)
        {
            is_locked = locked;
        }

        public OptionInt GetSelected()
        {
            return options[position];
        }

        public int GetSelectedValue()
        {
            return options[position].value;
        }

        public string GetSelectedTitle()
        {
            if (!string.IsNullOrWhiteSpace(options[position].title))
                return options[position].title;
            return options[position].value.ToString();
        }
    }
}