using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.Client
{

    public enum BoardRefType
    {
        None = 0,
        PackCard = 4,
    }

    /// <summary>
    /// A reference to a position on the board,
    /// It is currently being used by the PackOpen board
    /// </summary>

    public class BoardRef : MonoBehaviour
    {
        public BoardRefType type;
        public int index;
        public bool opponent;

        private static List<BoardRef> ref_list = new List<BoardRef>();

        void Awake()
        {
            ref_list.Add(this);
        }

        void OnDestroy()
        {
            ref_list.Remove(this);
        }

        public static BoardRef Get(BoardRefType type, bool opponent)
        {
            foreach (BoardRef bref in ref_list)
            {
                if (bref.type == type && bref.opponent == opponent)
                    return bref;
            }
            return null;
        }

        public static BoardRef Get(BoardRefType type, int index)
        {
            foreach (BoardRef bref in ref_list)
            {
                if (bref.type == type && bref.index == index)
                    return bref;
            }
            return null;
        }
    }
}
