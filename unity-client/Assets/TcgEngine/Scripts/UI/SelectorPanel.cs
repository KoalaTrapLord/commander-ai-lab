using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.UI
{
    public class SelectorPanel : UIPanel
    {
        private static List<SelectorPanel> panel_list = new List<SelectorPanel>();

        protected override void Awake()
        {
            base.Awake();
            panel_list.Add(this);
        }

        protected virtual void OnDestroy()
        {
            panel_list.Remove(this);
        }

        public virtual void Show(AbilityData ability, Card card)
        {
            //Override this to show panel
        }

        public virtual bool ShouldShow()
        {
            return false; //Override this function, when this panel should show
        }

        public static List<SelectorPanel> GetAll()
        {
            return panel_list;
        }

        public static void HideAll()
        {
            foreach (SelectorPanel panel in panel_list)
            {
                if(panel.IsVisible())
                    panel.Hide();
            }
        }
    }
}
