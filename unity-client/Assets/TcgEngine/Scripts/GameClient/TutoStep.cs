using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.UI;

namespace TcgEngine.Client
{
    /// <summary>
    /// TutoStep inside a group will all be triggered sequentially, game proceed to next step when end_trigger is met, or when another group is triggered
    /// </summary>

    public class TutoStep : UIPanel
    {
        [Header("Tuto Step")]
        public TutoEndTrigger end_trigger;
        public CardData trigger_target;
        public bool forced;                //Player MUST do the end_trigger action to proceed

        private TutoStepGroup group;
        private int step;
        private TutoBox tuto_box;

        private static List<TutoStep> steps = new List<TutoStep>();

        protected override void Awake()
        {
            base.Awake();
            step = transform.GetSiblingIndex();
            group = GetComponentInParent<TutoStepGroup>();
            tuto_box = GetComponentInChildren<TutoBox>();
            steps.Add(this);
        }

        protected override void Start()
        {
            base.Start();
            tuto_box.SetNextButton(end_trigger == TutoEndTrigger.Click);
        }

        protected virtual void OnDestroy()
        {
            steps.Remove(this);
        }

        public int GetStepIndex()
        {
            return step;
        }

        public static TutoStep Get(TutoStepGroup group, int step)
        {
            foreach (TutoStep s in steps)
            {
                if (s.group == group && s.step == step)
                    return s;
            }
            return null;
        }

        public static void HideAll()
        {
            foreach (TutoStep s in steps)
            {
                s.Hide();
            }
        }

    }

}
