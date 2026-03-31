using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    [System.Serializable]
    public class OptionString
    {
        public string value;
        public string title;
    }

    /// <summary>
    /// Option selector is a UI element with 2 arrows (left/right) to select an option among preset values
    /// This one let you select a string
    /// </summary>

    public class OptionSelector : MonoBehaviour
    {
        [Header("Options")]
        public OptionString[] options;

        [Header("Display")]
        public Text select_text;

        private int position = 0;

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
        }

        public void OnClickLeft()
        {
            position = (position + options.Length - 1) % options.Length;
            AfterChangeOption();
        }

        public void OnClickRight()
        {
            position = (position + options.Length + 1) % options.Length;
            AfterChangeOption();
        }

        public void SetIndex(int index)
        {
            position = index;
            AfterChangeOption();
        }

        public OptionString GetSelected()
        {
            return options[position];
        }

        public string GetSelectedValue()
        {
            return options[position].value;
        }

        public string GetSelectedTitle()
        {
            return options[position].title;
        }
    }
}