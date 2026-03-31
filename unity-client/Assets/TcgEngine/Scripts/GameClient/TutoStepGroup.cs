using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.Client
{
    /// <summary>
    /// TutoStep groups do NOT need to be triggered in order, group will be triggered on start_trigger condition 
    /// and then all TutoStep inside group will be executed in order.
    /// </summary>

    public class TutoStepGroup : MonoBehaviour
    {
        public int turn_min = 0;
        public int turn_max = 99;
        public TutoStartTrigger start_trigger;
        public CardData start_target;
        public bool forced; //Must finish all TutoStep inside group before triggering another group

        private bool triggered = false;

        private static List<TutoStepGroup> groups = new List<TutoStepGroup>();

        protected virtual void Awake()
        {
            groups.Add(this);
        }

        protected virtual void OnDestroy()
        {
            groups.Remove(this);
        }

        public void SetTriggered()
        {
            triggered = true;
        }

        public static TutoStepGroup Get(TutoStartTrigger trigger, int turn)
        {
            foreach (TutoStepGroup s in groups)
            {
                if (s.start_trigger == trigger && !s.triggered)
                {
                    if(turn >= s.turn_min&& turn <= s.turn_max)
                        return s;
                }
            }
            return null;
        }

        public static TutoStepGroup Get(TutoStartTrigger trigger, CardData target, int turn)
        {
            foreach (TutoStepGroup s in groups)
            {
                if (s.start_trigger == trigger && !s.triggered)
                {
                    if (turn >= s.turn_min && turn <= s.turn_max)
                    {
                        if (s.start_target == null || s.start_target == target)
                            return s;
                    }
                }
            }
            return null;
        }

    }
}
