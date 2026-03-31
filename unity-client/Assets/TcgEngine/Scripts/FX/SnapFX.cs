using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.FX
{
    /// <summary>
    /// FX that snap to another object (target), and follows it
    /// </summary>

    public class SnapFX : MonoBehaviour
    {
        public Transform target;
        public Vector3 offset = Vector3.zero;

        void Start()
        {

        }

        void Update()
        {
            if (target == null)
            {
                Destroy(gameObject);
                return;
            }

            transform.position = target.position + offset;
        }
    }
}
