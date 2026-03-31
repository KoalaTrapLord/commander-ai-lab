using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace TcgEngine
{
    /// <summary>
    /// Generic static functions for TcgEngine
    /// </summary>

    public static class GameTool
    {
        private const string uid_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
        private static System.Random random = new System.Random();

        //Generate a random string to use as UID
        public static string GenerateRandomID(int min = 9, int max = 15)
        {
            int length = random.Next(min, max);
            string unique_id = "";
            for (int i = 0; i < length; i++)
            {
                unique_id += uid_chars[random.Next(uid_chars.Length - 1)];
            }
            return unique_id;
        }

        //Generate a random int
        public static int GenerateRandomInt()
        {
            return random.Next(int.MinValue, int.MaxValue);
        }

        //Generate a random ulong
        public static ulong GenerateRandomUInt64()
        {
            ulong id = (uint)random.Next(int.MinValue, int.MaxValue); //Cast to uint before casting to ulong
            uint bid = (uint)random.Next(int.MinValue, int.MaxValue);
            id = id << 32;
            id = id | bid;
            return id;
        }

        //Pick X random elements in a list (same cant be picked twice, unless it appears twice or more in the list)
        public static List<T> PickXRandom<T>(List<T> source, List<T> dest, int x)
        {
            if (source.Count <= x || x <= 0)
                return source; //No need to pick anything

            if (dest.Count > 0)
                dest.Clear();

            for (int i = 0; i < x; i++)
            {
                int r = random.Next(source.Count);
                dest.Add(source[r]);
                source.RemoveAt(r);
            }

            return dest;
        }

        //Clone a list of string in most optimized way (avoiding as many Add/Remove as possible)
        public static void CloneList(List<string> source, List<string> dest)
        {
            for (int i = 0; i < source.Count; i++)
            {
                if (i < dest.Count)
                    dest[i] = source[i];
                else
                    dest.Add(source[i]);
            }

            if (dest.Count > source.Count)
                dest.RemoveRange(source.Count, dest.Count - source.Count);
        }

        //Clone a list in most optimized way, only the list is cloned, elements references are preserved
        public static void CloneListRef<T>(List<T> source, List<T> dest) where T : class
        {
            for (int i = 0; i < source.Count; i++)
            {
                if (i < dest.Count)
                    dest[i] = source[i];
                else
                    dest.Add(source[i]);
            }

            if (dest.Count > source.Count)
                dest.RemoveRange(source.Count, dest.Count - source.Count);
        }

        //Same a previous function, but elements could be null
        public static void CloneListRefNull<T>(List<T> source, ref List<T> dest) where T : class
        {
            //Source is null, set destination null
            if (source == null)
            {
                dest = null;
                return;
            }

            //Dest is null
            if (dest == null)
                dest = new List<T>();

            //Both arent null, clone
            CloneListRef(source, dest);
        }

        //Check if current device is mobile device
        public static bool IsMobile()
        {
#if UNITY_ANDROID || UNITY_IOS || UNITY_TIZEN
            return true;
#else
            return UnityEngine.Device.Application.isMobilePlatform;
#endif
        }

        //Check if using Universal Render Pipeline
        //If this function return compile error (because URP isnt installed and you dont want it, you can simply comment the code and return false
        public static bool IsURP()
        {
            if (GraphicsSettings.defaultRenderPipeline is UniversalRenderPipelineAsset)
                return true;
            return false;
        }

    }
}
