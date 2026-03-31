using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Icon that changes based on the value assigned
    /// </summary>

    public class IconValue : MonoBehaviour
    {
        public int value;
        public bool auto_refresh = true;

        public Sprite[] values;

        private Image image;

        void Awake()
        {
            image = GetComponent<Image>();
        }

        void Update()
        {
            if (auto_refresh)
                Refresh();
        }

        public void Refresh()
        {
            if (image == null)
                image = GetComponent<Image>();

            if (value >= 0 && value < values.Length)
            {
                image.sprite = values[value];
                image.enabled = image.sprite != null;
            }
        }

        public void SetMat(Material mat)
        {
            if (image == null)
                image = GetComponent<Image>();

            image.material = mat;
        }
    }
}
