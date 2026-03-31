using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Changes the color of a unity ui toggle text
    /// </summary>

    public class ToggleText : MonoBehaviour
    {
        public Color on_color = Color.yellow;
        public Color off_color = Color.white;

        private Toggle toggle;
        private Text toggle_txt;

        private bool previous = false;

        void Awake()
        {
            toggle = GetComponent<Toggle>();
            toggle_txt = GetComponentInChildren<Text>();
        }

        private void Start()
        {
            Refresh();
        }

        void Update()
        {
            if (previous != toggle.isOn)
                Refresh();
        }

        private void Refresh()
        {
            toggle_txt.color = toggle.isOn ? on_color : off_color;
            previous = toggle.isOn;
        }
    }
}
