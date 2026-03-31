using System.Collections;
using System.Collections.Generic;

namespace TcgEngine
{
    /// <summary>
    /// A pool reuses Memory for objects that are constantly created/destroyed, to prevent always allocating more memory
    /// Makes the AI much much much faster
    /// </summary>

    public class Pool<T> where T : new()
    {
        private HashSet<T> in_use = new HashSet<T>();
        private Stack<T> available = new Stack<T>();

        public T Create()
        {
            if (available.Count > 0)
            {
                T elem = available.Pop();
                in_use.Add(elem);
                return elem;
            }
            T new_obj = new T();
            in_use.Add(new_obj);
            return new_obj;
        }

        public void Dispose(T elem)
        {
            in_use.Remove(elem);
            available.Push(elem);
        }

        public void DisposeAll()
        {
            foreach (T obj in in_use)
                available.Push(obj);
            in_use.Clear();
        }

        public void Clear()
        {
            in_use.Clear();
            available.Clear();
        }

        public HashSet<T> GetAllActive()
        {
            return in_use;
        }

        public int Count
        {
            get { return in_use.Count; }
        }

        public int CountAvailable
        {
            get { return available.Count; }
        }

        public int CountCapacity
        {
            get { return in_use.Count + available.Count; }
        }
    }
}
