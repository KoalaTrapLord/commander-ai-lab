using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Useful optimization tool, let you use arrays without instantiating new ones
    /// </summary>

    public class ListSwap<T>
    {
        public List<T> swap1 = new List<T>();
        public List<T> swap2 = new List<T>();

        //Return any array
        public List<T> Get()
        {
            swap1.Clear(); //Clear before using
            return swap1;
        }

        //Return the OTHER array (because skip is already in use)
        public List<T> GetOther(List<T> skip)
        {
            if (skip == swap1)
            {
                swap2.Clear(); //Clear before using
                return swap2;
            }
            swap1.Clear(); //Clear before using
            return swap1;
        }

        //Clear both
        public void Clear()
        {
            swap1.Clear();
            swap2.Clear();
        }
    }
}
