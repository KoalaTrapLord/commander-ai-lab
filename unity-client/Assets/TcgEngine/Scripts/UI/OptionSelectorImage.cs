using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    [System.Serializable]
    public class OptionImage
    {
        public string value;
        public Sprite image;
    }

    /// <summary>
    /// Option selector is a UI element with 2 arrows (left/right) to select an option among preset values
    /// This one let you select a sprite
    /// </summary>

    public class OptionSelectorImage : MonoBehaviour
    {
        [Header("Options")]
        public OptionImage[] options;

        [Header("Display")]
        public Image select_img;

        public UnityAction onChange;

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
            if (select_img != null)
                select_img.sprite = GetSelectedImage();
            onChange?.Invoke();
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

        public void SetValue(string value)
        {
            for (int i = 0; i < options.Length; i++)
            {
                if (options[i].value == value)
                    position = i;
            }

            if (select_img != null)
                select_img.sprite = GetSelectedImage();
        }

        public OptionImage GetSelected()
        {
            return options[position];
        }

        public string GetSelectedValue()
        {
            return options[position].value;
        }

        public Sprite GetSelectedImage()
        {
            return options[position].image;
        }
    }
}