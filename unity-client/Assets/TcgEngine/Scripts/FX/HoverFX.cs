using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.FX
{
    /// <summary>
    /// FX that appear when hovering a target
    /// </summary>

    public class HoverFX : MonoBehaviour
    {
        public GameObject fx;

        private bool hover = false;

        void Start()
        {

        }

        void Update()
        {
            if (hover != fx.activeSelf)
                fx.SetActive(hover);
        }

        public void PointerEnter()
        {
            hover = true;
        }

        public void PointerExit()
        {
            hover = false;
        }
    }
}
