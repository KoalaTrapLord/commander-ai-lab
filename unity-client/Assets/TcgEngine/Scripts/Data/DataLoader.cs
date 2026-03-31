using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine
{

    /// <summary>
    /// This script initiates loading all the game data
    /// </summary>

    public class DataLoader : MonoBehaviour
    {
        public GameplayData data;
        public AssetData assets;

        private HashSet<string> card_ids = new HashSet<string>();
        private HashSet<string> ability_ids = new HashSet<string>();
        private HashSet<string> deck_ids = new HashSet<string>();

        private static DataLoader instance;

        void Awake()
        {
            instance = this;
            LoadData();
        }

        public void LoadData()
        {
            //To make loading faster, add a path inside each Load() function, relative to Resources folder
            //For example CardData.Load("Cards");  to only load data inside the Resources/Cards folder
            CardData.Load();
            TeamData.Load();
            RarityData.Load();
            TraitData.Load();
            VariantData.Load();
            PackData.Load();
            LevelData.Load();
            DeckData.Load();
            AbilityData.Load();
            StatusData.Load();
            AvatarData.Load();
            CardbackData.Load();
            RewardData.Load();

            CheckCardData();
            CheckAbilityData();
            CheckDeckData();
            CheckVariantData();
        }

        //Make sure the data is valid
        private void CheckCardData()
        {
            card_ids.Clear();
            foreach (CardData card in CardData.GetAll())
            {
                if (string.IsNullOrEmpty(card.id))
                    Debug.LogError(card.name + " id is empty");
                if (card_ids.Contains(card.id))
                    Debug.LogError("Dupplicate Card ID: " + card.id);

                if (card.team == null)
                    Debug.LogError(card.id + " team is null");
                if (card.rarity == null)
                    Debug.LogError(card.id + " rarity is null");

                foreach (TraitData trait in card.traits)
                {
                    if (trait == null)
                        Debug.LogError(card.id + " has null trait");
                }

                if (card.stats != null)
                {
                    foreach (TraitStat stat in card.stats)
                    {
                        if (stat.trait == null)
                            Debug.LogError(card.id + " has null stat trait");
                    }
                }

                foreach (AbilityData ability in card.abilities)
                {
                    if(ability == null)
                        Debug.LogError(card.id + " has null ability");
                }

                card_ids.Add(card.id);
            }
        }

        //Make sure the data is valid
        private void CheckAbilityData()
        {
            ability_ids.Clear();
            foreach (AbilityData ability in AbilityData.GetAll())
            {
                if (string.IsNullOrEmpty(ability.id))
                    Debug.LogError(ability.name + " id is empty");
                if (ability_ids.Contains(ability.id))
                    Debug.LogError("Dupplicate Ability ID: " + ability.id);

                foreach (AbilityData chain in ability.chain_abilities)
                {
                    if (chain == null)
                        Debug.LogError(ability.id + " has null chain ability");
                }

                ability_ids.Add(ability.id);
            }
        }

        //Make sure the data is valid
        private void CheckDeckData()
        {
            GameplayData gdata = GameplayData.Get();
            CheckDeckArray(gdata.ai_decks);
            CheckDeckArray(gdata.free_decks);
            CheckDeckArray(gdata.starter_decks);

            if(gdata.test_deck == null || gdata.test_deck_ai == null)
                Debug.Log("Deck is null in Resources/GameplayData");

            deck_ids.Clear();
            foreach (DeckData deck in DeckData.GetAll())
            {
                if (string.IsNullOrEmpty(deck.id))
                    Debug.LogError(deck.name + " id is empty");
                if (deck_ids.Contains(deck.id))
                    Debug.LogError("Dupplicate Deck ID: " + deck.id);

                foreach (CardData card in deck.cards)
                {
                    if (card == null)
                        Debug.LogError(deck.id + " has null card");
                }

                deck_ids.Add(deck.id);
            }
        }

        private void CheckDeckArray(DeckData[] decks)
        {
            foreach (DeckData deck in decks)
            {
                if (deck == null)
                    Debug.Log("Deck is null in Resources/GameplayData");
            }
        }

        private void CheckVariantData()
        {
            VariantData dvariant = VariantData.GetDefault();
            if(dvariant == null)
                Debug.LogError("No default variant data found, make sure you have a default VariantData");
        }

        public static DataLoader Get()
        {
            return instance;
        }
    }
}