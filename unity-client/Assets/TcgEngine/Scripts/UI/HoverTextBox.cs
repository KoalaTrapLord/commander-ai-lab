using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Box that appears when hovering a HoverTarget
    /// </summary>

    public class HoverTextBox : MonoBehaviour
    {
        public UIPanel panel_left;
        public UIPanel panel_right;
        public Text text1;
        public Text text2;

        private HoverTarget current;
        private HoverTargetUI current_ui;

        private RectTransform rect_left;
        private RectTransform rect_right;

        private static HoverTextBox instance;

        void Awake()
        {
            instance = this;
            rect_left = panel_left.GetComponent<RectTransform>();
            rect_right = panel_right.GetComponent<RectTransform>();
        }

        void Update()
        {
            if (current != null || current_ui != null)
            {
                transform.position = GameUI.MouseToWorld(MouseInput.GetMousePosition());
                transform.rotation = Quaternion.LookRotation(Camera.main.transform.forward, Vector2.up);
                panel_left.SetVisible(transform.position.x > 0f);
                panel_right.SetVisible(transform.position.x <= 0f);

                if (current != null && !current.IsHover())
                    Hide();
                if (current_ui != null && !current_ui.IsHover())
                    Hide();
            }
        }

        public void Show(HoverTarget hover)
        {
            current = hover;
            current_ui = null;
            text1.text = hover.GetText();
            text2.text = hover.GetText();
            text1.fontSize = hover.text_size;
            text2.fontSize = hover.text_size;
            rect_left.sizeDelta = new Vector2(hover.width, hover.height);
            rect_right.sizeDelta = new Vector2(hover.width, hover.height);
        }

        public void Show(HoverTargetUI hover)
        {
            current = null;
            current_ui = hover;
            text1.text = hover.GetText();
            text2.text = hover.GetText();
            text1.fontSize = hover.text_size;
            text2.fontSize = hover.text_size;
            rect_left.sizeDelta = new Vector2(hover.width, hover.height);
            rect_right.sizeDelta = new Vector2(hover.width, hover.height);
        }

        public void Hide()
        {
            current = null;
            current_ui = null;
            panel_left.Hide();
            panel_right.Hide();
        }

        public static HoverTextBox Get()
        {
            return instance;
        }
    }
}