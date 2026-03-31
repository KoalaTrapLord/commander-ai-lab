using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.AI;

namespace TcgEngine
{
    /// <summary>
    /// Generic gameplay settings, such as starting stats, decks limit, scenes, and ai level
    /// </summary>

    [CreateAssetMenu(fileName = "GameplayData", menuName = "TcgEngine/GameplayData", order = 0)]
    public class GameplayData : ScriptableObject
    {
        [Header("Gameplay")]
        public int hp_start = 20;
        public int mana_start = 1;
        public int mana_per_turn = 1;
        public int mana_max = 10;
        public int cards_start = 5;
        public int cards_per_turn = 1;
        public int cards_max = 10;
        public float turn_duration = 30f;
        public CardData second_bonus;
        public bool mulligan;

        [Header("Deckbuilding")]
        public int deck_size = 30;
        public int deck_duplicate_max = 2;

        [Header("Buy/Sell")]
        public float sell_ratio = 0.8f;

        [Header("AI")]
        public AIType ai_type;              //AI algorythm
        public int ai_level = 10;           //AI level, 10=best, 1=weakest

        [Header("Decks")]
        public DeckData[] free_decks;       //These decks are always available in menu, useful for tests
        public DeckData[] starter_decks;    //When API is enabled, each player can select ONE of those
        public DeckData[] ai_decks;         //When player solo, AI will pick one of these at random

        [Header("Scenes")]
        public string[] arena_list;         //List of game scenes

        [Header("Test")]
        public DeckData test_deck;          //For when starting the game directly from Unity game scene
        public DeckData test_deck_ai;       //For when starting the game directly from Unity game scene
        public bool ai_vs_ai;

        public int GetPlayerLevel(int xp)
        {
            return Mathf.FloorToInt(xp / 1000f) + 1;
        }

        public string GetRandomArena()
        {
            if (arena_list.Length > 0)
                return arena_list[Random.Range(0, arena_list.Length)];
            return "Game";
        }

        public DeckData GetRandomFreeDeck()
        {
            if (free_decks.Length > 0)
                return free_decks[Random.Range(0, free_decks.Length)];
            return null;
        }

        public DeckData GetRandomAIDeck()
        {
            if (ai_decks.Length > 0)
                return ai_decks[Random.Range(0, ai_decks.Length)];
            return null;
        }

        public static GameplayData Get()
        {
            return DataLoader.Get().data;
        }
    }
}