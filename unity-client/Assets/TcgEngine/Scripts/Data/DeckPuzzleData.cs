using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Deck with more fields for having specific cards or starting board cards
    /// </summary>

    [System.Serializable]
    public class DeckCardSlot
    {
        public CardData card;
        public SlotXY slot;
    }

    [CreateAssetMenu(fileName = "DeckPuzzleData", menuName = "TcgEngine/DeckPuzzleData", order = 7)]
    public class DeckPuzzleData : DeckData
    {
        public DeckCardSlot[] board_cards;
        public int start_cards = 5;
        public int start_mana = 2;
        public int start_hp = 20;
        public bool dont_shuffle_deck;

        public static new DeckPuzzleData Get(string id)
        {
            foreach (DeckData deck in GetAll())
            {
                if (deck.id == id && deck is DeckPuzzleData)
                    return (DeckPuzzleData) deck;
            }
            return null;
        }
    }
}
