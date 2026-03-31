using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Class that simplifies the code for waiting for X seconds or waiting for condition
    /// Also allows to call coroutines outside of a MonoBehaviour
    /// </summary>

    public class TimeTool
    {
        //--- Coroutine Code ----

        public static void WaitFor(float time, Action callback)
        {
            StartCoroutine(WaitForRun(time, callback));
        }

        public static void WaitUntil(Func<bool> condition, Action callback)
        {
            StartCoroutine(WaitUntilRun(condition, callback));
        }

        private static IEnumerator WaitForRun(float time, Action callback) { yield return new WaitForSeconds(time); callback?.Invoke(); }
        private static IEnumerator WaitUntilRun(Func<bool> condition, Action callback) { yield return new WaitUntil(condition); callback?.Invoke(); }

        public static Coroutine StartCoroutine(IEnumerator routine)
        {
            return TimeToolMono.Inst.StartCoroutine(routine);
        }

        public static void StopCoroutine(Coroutine routine)
        {
            TimeToolMono.Inst.StopCoroutine(routine);
        }

        //--- Tasks Code ----

        //Do not use Task.Delay since its broken on some platform (like WebGl), use this instead
        public static async Task Delay(int miliseconds)
        {
#if UNITY_WEBGL
            //WebGL Task.Delay is broken
            float seconds = miliseconds / 1000f;
            float start_time = Time.time;
            while (Time.time < start_time + seconds)
                await Task.Yield();
#else
            //More performant on desktop/mobile
            await Task.Delay(miliseconds); 
#endif
        }

    }
}
