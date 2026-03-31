using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Defines all traits and stats data
    /// </summary>

    [CreateAssetMenu(fileName = "TraitData", menuName = "TcgEngine/TraitData", order = 1)]
    public class TraitData : ScriptableObject
    {
        public string id;
        public string title;
        public Sprite icon;

        public static List<TraitData> trait_list = new List<TraitData>();

        public string GetTitle()
        {
            return title;
        }

        public static void Load(string folder = "")
        {
            if (trait_list.Count == 0)
                trait_list.AddRange(Resources.LoadAll<TraitData>(folder));
        }

        public static TraitData Get(string id)
        {
            foreach (TraitData team in GetAll())
            {
                if (team.id == id)
                    return team;
            }
            return null;
        }

        public static List<TraitData> GetAll()
        {
            return trait_list;
        }
    }

    [System.Serializable]
    public struct TraitStat
    {
        public TraitData trait;
        public int value;
    }
}