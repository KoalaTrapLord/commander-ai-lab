using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Events;

namespace TcgEngine.UI
{
    /// <summary>
    /// A toggle button that let you change tab panel
    /// </summary>

    public class TabButton : MonoBehaviour
    {
        public string group;
        public bool active;
        public GameObject highlight;
        public UIPanel ui_panel;

        public UnityAction onClick;
        public static UnityAction<TabButton> onClickAny;

        private static List<TabButton> tab_list = new List<TabButton>();

        private void Awake()
        {
            tab_list.Add(this);
        }

        private void OnDestroy()
        {
            tab_list.Remove(this);
        }

        void Start()
        {
            Button button = GetComponent<Button>();
            if (button != null)
                button.onClick.AddListener(OnClick);

            if (active && ui_panel != null)
                ui_panel.Show();
        }

        void Update()
        {
            if (highlight != null)
                highlight.SetActive(active);
        }

        private void OnClick()
        {
            Activate();
            onClick?.Invoke();
            onClickAny?.Invoke(this);
        }

        public void Activate()
        {
            SetAll(group, false);
            active = true;
            if (ui_panel != null)
                ui_panel.Show();
        }

        public void Deactivate()
        {
            active = false;
            if (ui_panel != null)
                ui_panel.Hide();
        }

        public bool IsActive()
        {
            return active;
        }

        public static void SetAll(string group, bool act)
        {
            foreach (TabButton btn in tab_list)
            {
                if (btn.group == group)
                {
                    btn.active = act;
                    if(btn.ui_panel != null)
                        btn.ui_panel.SetVisible(act);
                }
            }
        }

        public static List<TabButton> GetAll(string group)
        {
            List<TabButton> glist = new List<TabButton>();
            foreach (TabButton btn in tab_list)
            {
                if (btn.group == group)
                    glist.Add(btn);
            }
            return glist;
        }

        public static List<TabButton> GetAll()
        {
            return tab_list;
        }
    }
}
