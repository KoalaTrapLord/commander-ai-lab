using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Defines all factions data
    /// </summary>
    
    [CreateAssetMenu(fileName = "TeamData", menuName = "TcgEngine/TeamData", order = 1)]
    public class TeamData : ScriptableObject
    {
        public string id;
        public string title;
        public Sprite icon;
        public Color color;

        public static List<TeamData> team_list = new List<TeamData>();

        public static void Load(string folder = "")
        {
            if (team_list.Count == 0)
                team_list.AddRange(Resources.LoadAll<TeamData>(folder));
        }

        public static TeamData Get(string id)
        {
            foreach (TeamData team in GetAll())
            {
                if (team.id == id)
                    return team;
            }
            return null;
        }

        public static List<TeamData> GetAll()
        {
            return team_list;
        }
    }
}