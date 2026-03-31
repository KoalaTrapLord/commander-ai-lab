using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    public class TimeToolMono : MonoBehaviour
    {
        private static TimeToolMono _instance;

        public Coroutine StartRoutine(IEnumerator routine)
        {
            return StartCoroutine(routine);
        }

        public void StopRoutine(Coroutine routine)
        {
            StopCoroutine(routine);
        }

        public static TimeToolMono Inst
        {
            get
            {
                if (_instance == null)
                {
                    GameObject ntool = new GameObject("TimeTool");
                    _instance = ntool.AddComponent<TimeToolMono>();
                }
                return _instance;
            }
        }
    }
}
