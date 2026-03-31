using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// UI element that shows a value with a progress bar
    /// </summary>

    public class ProgressBar : MonoBehaviour
    {
        public float value;
        public float value_max;

        public Image fill;

        void Start()
        {

        }

        void Update()
        {
            float ratio = value / Mathf.Max(value_max, 0.01f);
            fill.fillAmount = ratio;
        }
    }
}