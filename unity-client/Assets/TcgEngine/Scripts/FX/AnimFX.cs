using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;

namespace TcgEngine.FX
{
    /// <summary>
    /// Useful tool to define animation sequences
    /// </summary>

    public class AnimFX : MonoBehaviour
    {
        private GameObject target;
        private float timer = 0f;

        private Vector3 start_pos;
        private Vector3 current_pos;

        private AnimAction current = null;
        private Queue<AnimAction> sequence = new Queue<AnimAction>();

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
                start_pos = target.transform.position;
                current_pos = target.transform.position;
                timer = 0f;
            }

            if (current != null)
            {
                if (timer < current.duration)
                {
                    timer += Time.deltaTime;

                    if (current.type == AnimActionType.Move)
                    {
                        float dist = (current.target_pos - start_pos).magnitude;
                        float speed = dist / Mathf.Max(current.duration, 0.01f);
                        current_pos = Vector3.MoveTowards(current_pos, current.target_pos, speed * Time.deltaTime);
                        transform.position = current_pos;
                    }

                    if (current.type == AnimActionType.Size)
                    {
                        float dist = Mathf.Abs(transform.localScale.y - current.value);
                        float speed = dist / Mathf.Max(current.duration, 0.01f);
                        transform.localScale = Vector3.MoveTowards(transform.localScale, current.value * Vector3.one, speed * Time.deltaTime);
                    }
                }
                else
                {
                    current.callback?.Invoke();
                    current = null;
                }
            }
        }

        public void MoveTo(Vector3 pos, float duration)
        {
            AnimAction action = new AnimAction();
            action.type = AnimActionType.Move;
            action.duration = duration;
            action.target_pos = pos;
            sequence.Enqueue(action);
        }

        public void ScaleTo(float value, float duration)
        {
            AnimAction action = new AnimAction();
            action.type = AnimActionType.Size;
            action.duration = duration;
            action.value = value;
            sequence.Enqueue(action);
        }

        public void Callback(float duration, UnityAction callback)
        {
            AnimAction action = new AnimAction();
            action.type = AnimActionType.None;
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

        public static AnimFX Create(GameObject target)
        {
            AnimFX anim = target.GetComponent<AnimFX>();
            if (anim == null)
                anim = target.AddComponent<AnimFX>();

            anim.Clear();
            anim.target = target;
            return anim;
        }
    }

    public enum AnimActionType
    {
        None = 0,
        Move = 5,
        Size = 10,
    }

    public class AnimAction
    {
        public AnimActionType type;
        public Vector3 target_pos;
        public float value = 0f;
        public float duration = 1f;
        public UnityAction callback = null;
    }

}