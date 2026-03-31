using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Add to any UI element to make it resize on mobile (some buttons should be bigger on mobile)
    /// </summary>

    public class MobileResizeUI : MonoBehaviour
    {
        public Vector2 position_offset;
        public float size = 1f;

        void Start()
        {
            if (GameTool.IsMobile())
            {
                RectTransform rect = GetComponent<RectTransform>();
                rect.anchoredPosition += position_offset;
                transform.localScale = transform.localScale * size;
            }
        }
    }
}