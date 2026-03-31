using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;

namespace TcgEngine.FX
{
    /// <summary>
    /// Useful tool to define animation sequences on materials
    /// </summary>

    public class AnimMatFX : MonoBehaviour
    {
        private Material target;
        private float timer = 0f;

        private float start_val;
        private float current_val;

        private AnimMatAction current = null;
        private Queue<AnimMatAction> sequence = new Queue<AnimMatAction>();

        void Start()
        {

        }

        void Update()
        {
            if (target == null)
                return;

            if (current == null && sequence.Count > 0)
            {
                current = sequence.Dequeue();
                start_val = target.GetFloat(current.target_name);
                current_val = start_val;
                timer = 0f;
            }

            if (current != null)
            {
                if (timer < current.duration)
                {
                    timer += Time.deltaTime;

                    if (current.type == AnimMatActionType.Float)
                    {
                        float dist = Mathf.Abs(current.target_value - start_val);
                        float speed = dist / Mathf.Max(current.duration, 0.01f);
                        current_val = Mathf.MoveTowards(current_val, current.target_value, speed * Time.deltaTime);
                        target.SetFloat(current.target_name, current_val);
                    }
                }
                else
                {
                    current.callback?.Invoke();
                    current = null;
                }
            }
        }

        public void SetFloat(string name, float value, float duration)
        {
            AnimMatAction action = new AnimMatAction();
            action.type = AnimMatActionType.Float;
            action.duration = duration;
            action.target_name = name;
            action.target_value = value;
            sequence.Enqueue(action);
        }

        public void Callback(float duration, UnityAction callback)
        {
            AnimMatAction action = new AnimMatAction();
            action.type = AnimMatActionType.None;
            action.duration = duration;
            action.callback = callback;
            sequence.Enqueue(action);
        }

        public void Clear()
        {
            target = null;
            timer = 0f;
            sequence.Clear();
        }

        public static AnimMatFX Create(GameObject obj, Material target)
        {
            AnimMatFX anim = obj.GetComponent<AnimMatFX>();
            if (anim == null)
                anim = obj.AddComponent<AnimMatFX>();

            anim.Clear();
            anim.target = target;
            return anim;
        }
    }

    public enum AnimMatActionType
    {
        None = 0,
        Float = 5,
    }

    public class AnimMatAction
    {
        public AnimMatActionType type;
        public string target_name;
        public float target_value;
        public float duration = 1f;
        public UnityAction callback = null;
    }

}