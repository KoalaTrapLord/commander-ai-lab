using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Select a value between min and max
    /// </summary>

    public class NumberSelector : MonoBehaviour
    {
        [Header("Options")]
        public int value;
        public int value_min;
        public int value_max;

        [Header("Display")]
        public Text select_text;

        public UnityAction onChange;

        private bool is_locked = false;

        void Start()
        {
            SetValue(0);
        }

        void Update()
        {

        }

        private void AfterChangeOption()
        {
            if (select_text != null)
                select_text.text = value.ToString();
            onChange?.Invoke();
        }

        public void OnClickLeft()
        {
            if (is_locked)
                return;

            value--;
            value = Mathf.Clamp(value, value_min, value_max);
            AfterChangeOption();
        }

        public void OnClickRight()
        {
            if (is_locked)
                return;

            value++;
            value = Mathf.Clamp(value, value_min, value_max);
            AfterChangeOption();
        }

        public void SetValue(int val)
        {
            value = Mathf.Clamp(val, value_min, value_max);

            if (select_text != null)
                select_text.text = value.ToString();
        }

        public void SetMin(int min)
        {
            value_min = min;
        }

        public void SetMax(int max)
        {
            value_max = max;
        }

        public void SetLocked(bool locked)
        {
            is_locked = locked;
        }

    }
}