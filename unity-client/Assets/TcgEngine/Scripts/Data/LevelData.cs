using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{

    [CreateAssetMenu(fileName = "LevelData", menuName = "TcgEngine/LevelData", order = 7)]
    public class LevelData : ScriptableObject
    {
        public string id;
        public int level;

        [Header("Display")]
        public string title;

        [Header("Gameplay")]
        public string scene;
        public DeckData player_deck;
        public DeckData ai_deck;
        public int ai_level = 10; //From 1 to 10
        public float turn_duration = 9999f;
        public LevelFirst first_player;
        public GameObject tuto_prefab;
        public bool mulligan = true;

        [Header("Rewards")]
        public int reward_xp = 100;
        public int reward_coins = 100;
        public PackData[] reward_packs;
        public CardData[] reward_cards;
        public DeckData[] reward_decks;

        public static List<LevelData> level_list = new List<LevelData>();

        public static void Load(string folder = "")
        {
            if (level_list.Count == 0)
            {
                level_list.AddRange(Resources.LoadAll<LevelData>(folder));
                level_list.Sort((LevelData a, LevelData b) => { return a.level.CompareTo(b.level); });
            }
        }

        public string GetTitle()
        {
            return title;
        }

        public static LevelData Get(string id)
        {
            foreach (LevelData level in GetAll())
            {
                if (level.id == id)
                    return level;
            }
            return null;
        }

        public static List<LevelData> GetAll()
        {
            return level_list;
        }
    }

    public enum LevelFirst
    {
        Random = 0,
        Player = 10,
        AI = 20,
    }
}