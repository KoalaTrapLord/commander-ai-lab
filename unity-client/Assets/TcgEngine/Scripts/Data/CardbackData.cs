using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Defines all cardback data
    /// </summary>

    [CreateAssetMenu(fileName = "Cardback", menuName = "TcgEngine/Cardback", order = 10)]
    public class CardbackData : ScriptableObject
    {
        public string id;
        public Sprite cardback;
        public Sprite deck;
        public int sort_order;

        public static List<CardbackData> cardback_list = new List<CardbackData>();

        public static void Load(string folder = "")
        {
            if (cardback_list.Count == 0)
                cardback_list.AddRange(Resources.LoadAll<CardbackData>(folder));

            cardback_list.Sort((CardbackData a, CardbackData b) => {
                if (a.sort_order == b.sort_order)
                    return a.id.CompareTo(b.id);
                else
                    return a.sort_order.CompareTo(b.sort_order);
            });
        }

        public static CardbackData Get(string id)
        {
            foreach (CardbackData cardback in GetAll())
            {
                if (cardback.id == id)
                    return cardback;
            }
            return null;
        }

        public static List<CardbackData> GetAll()
        {
            return cardback_list;
        }
    }
}
