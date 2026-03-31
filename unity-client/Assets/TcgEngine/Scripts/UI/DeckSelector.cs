using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Deck selector is a dropdown that let the player select a deck before a match
    /// </summary>

    public class DeckSelector : MonoBehaviour
    {
        public DropdownValue deck_dropdown;

        public UnityAction<string> onChange;

        void Start()
        {
            deck_dropdown.onValueChanged += OnChange;
        }

        void Update()
        {

        }

        public void SetupUserDeckList()
        {
            deck_dropdown.ClearOptions();

            deck_dropdown.AddOption("random", "Random");

            //Add standard decks
            foreach (DeckData deck in GameplayData.Get().free_decks)
            {
                deck_dropdown.AddOption(deck.id, deck.title);
            }

            UserData udata = Authenticator.Get().UserData;
            if (udata != null)
            {
                foreach (UserDeckData deck in udata.decks)
                {
                    if (udata.IsDeckValid(deck))
                    {
                        deck_dropdown.AddOption(deck.tid, deck.title);
                    }
                }
            }
        }

        public void SetupAIDeckList()
        {
            deck_dropdown.ClearOptions();

            deck_dropdown.AddOption("random_ai", "Random");

            //Add standard decks
            foreach (DeckData deck in GameplayData.Get().ai_decks)
            {
                deck_dropdown.AddOption(deck.id, deck.title);
            }

            //Also add user made decks
            UserData udata = Authenticator.Get().UserData;
            if (udata != null)
            {
                foreach (UserDeckData deck in udata.decks)
                {
                    if (udata.IsDeckValid(deck))
                    {
                        deck_dropdown.AddOption(deck.tid, deck.title);
                    }
                }
            }
        }

        private void SelectDeck(UserDeckData deck)
        {
            if (deck != null)
            {
                deck_dropdown.SetValue(deck.tid);
            }
        }

        private void SelectDeck(DeckData deck)
        {
            if (deck != null)
            {
                deck_dropdown.SetValue(deck.id);
            }
        }

        public void SelectDeck(string deck)
        {
            //Make sure deck exists, to prevent assigning invalid deck
            UserData udata = Authenticator.Get().UserData;
            UserDeckData udeck = udata?.GetDeck(deck);
            if (udeck != null)
            {
                SelectDeck(udeck);
                return;
            }

            DeckData adeck = DeckData.Get(deck);
            if(adeck != null)
                SelectDeck(adeck);
        }

        public void SelectDeck(int index)
        {
            deck_dropdown.SetValue(index);
        }

        public void Lock()
        {
            deck_dropdown.interactable = false;
        }

        public void Unlock()
        {
            deck_dropdown.interactable = true;
        }

        public void SetLocked(bool locked)
        {
            deck_dropdown.interactable = !locked;
        }

        private void OnChange(int i, string val)
        {
            string value = deck_dropdown.GetSelectedValue();
            onChange?.Invoke(value);
        }

        public string GetDeckID()
        {
            return deck_dropdown.GetSelectedValue();
        }

        public string GetDeckTitle()
        {
            return deck_dropdown.GetSelectedText();
        }

        public UserDeckData GetDeckById(string deck_id)
        {
            UserData user = Authenticator.Get().UserData;
            UserDeckData udeck = user.GetDeck(deck_id); //Check for user custom deck
            DeckData deck = DeckData.Get(deck_id);     //Check for deck presets

            //User custom deck
            if (udeck != null)
                return udeck;
            //Premade deck
            else if (deck != null)
                return new UserDeckData(deck);
            return null;
        }

        public UserDeckData GetDeck()
        {
            string deck_id = GetDeckID();

            //Random Reck
            if (deck_id == "random")
                return GetRandomDeck();
            if (deck_id == "random_ai")
                return GetRandomDeckAI();

            return GetDeckById(deck_id);
        }

        public UserDeckData GetRandomDeck()
        {
            List<UserDeckData> random_decks = new List<UserDeckData>();
            foreach (DropdownValueItem item in deck_dropdown.Items)
            {
                UserDeckData deck = GetDeckById(item.id);
                if (deck != null)
                    random_decks.Add(deck);
            }

            if (random_decks.Count > 0)
                return random_decks[Random.Range(0, random_decks.Count)];
            return null;
        }

        public UserDeckData GetRandomDeckAI()
        {
            return new UserDeckData(GameplayData.Get().GetRandomAIDeck());
        }
    }
}