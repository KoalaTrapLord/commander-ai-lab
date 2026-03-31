using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Events;

namespace TcgEngine.UI
{
    /// <summary>
    /// A toggle button that will disable other buttons in same group when clicked
    /// </summary>

    public class IconButton : MonoBehaviour
    {
        public string group;
        public string value;

        public Image active_img;
        public Image disabled_img;
        public bool on_if_all_off;

        public UnityAction<IconButton> onClick;

        private bool active = false;
        private Button button;
        private static List<IconButton> toggle_list = new List<IconButton>();

        void Awake()
        {
            toggle_list.Add(this);
            button = GetComponent<Button>();
            button.onClick.AddListener(OnClick);

            if(!on_if_all_off && active_img != null)
                active_img.enabled = false;
        }

        private void OnDestroy()
        {
            toggle_list.Remove(this);
        }

        void Start()
        {

        }

        private void Update()
        {
            if (on_if_all_off)
            {
                if (active_img != null && IsAllOff(group))
                {
                    active_img.enabled = true;
                }
            }
        }

        void OnClick()
        {
            bool was_active = active;

            DeactivateAll(group);

            if (!was_active)
                Activate();

            if (onClick != null)
                onClick.Invoke(this);
        }

        public void SetActive(bool act)
        {
            if (act) Activate();
            else Deactivate();
        }

        public void Activate()
        {
            active = true;
            if (active_img != null)
                active_img.enabled = true;
        }

        public void Deactivate()
        {
            active = false;
            if (active_img != null)
                active_img.enabled = false;
        }

        public bool IsActive()
        {
            return active;
        }

        public static bool IsAllOff(string group)
        {
            bool all_off = true;
            foreach (IconButton toggle in toggle_list)
            {
                if (toggle.group == group && toggle.IsActive())
                    all_off = false;
            }
            return all_off;
        }

        public static void DeactivateAll(string group)
        {
            foreach (IconButton toggle in toggle_list)
            {
                if (toggle.group == group)
                    toggle.Deactivate();
            }
        }

        public static List<IconButton> GetAll(string group)
        {
            List<IconButton> toggles = new List<IconButton>();
            foreach (IconButton toggle in toggle_list)
            {
                if (toggle.group == group)
                    toggles.Add(toggle);
            }
            return toggles;
        }
    }
}