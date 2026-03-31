using System.Collections;
using System.Collections.Generic;
using UnityEngine.UI;
using TcgEngine.Client;

namespace TcgEngine.UI
{

    public class SoloPanel : UIPanel
    {
        public Text username;
        public DeckSelector selector_player;
        public DeckSelector selector_ai;

        public DeckDisplay display_player;
        public DeckDisplay display_ai;

        private static SoloPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
        }

        protected override void Start()
        {
            base.Start();

            selector_player.onChange += OnChangeDeck;
            selector_ai.onChange += OnChangeDeck;
        }

        private void RefreshDecks()
        {
            if(username != null)
                username.text = Authenticator.Get().Username;

            string selected_id = MainMenu.Get().deck_selector.GetDeckID();
            selector_player.SetupUserDeckList();
            selector_player.SelectDeck(selected_id);
            selector_ai.SetupAIDeckList();
            selector_ai.SelectDeck(0);

            RefreshDeckDisplay();
        }

        private void RefreshDeckDisplay()
        {
            display_player.SetDeck(selector_player.GetDeckID());
            display_ai.SetDeck(selector_ai.GetDeckID());
        }

        private void OnChangeDeck(string id)
        {
            RefreshDeckDisplay();
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshDecks();
        }

        public void OnClickPlay()
        {
            UserDeckData deck = selector_player.GetDeck();
            if (deck == null || !deck.IsValid())
                return;

            UserDeckData aideck = selector_ai.GetDeck();
            if (aideck == null || !aideck.IsValid())
                return;

            GameClient.player_settings.deck = deck;
            GameClient.ai_settings.deck = aideck;
            GameClient.ai_settings.ai_level = GameplayData.Get().ai_level;
            GameClient.game_settings.scene = GameplayData.Get().GetRandomArena();

            MainMenu.Get().StartGame(GameType.Solo, GameMode.Casual);
        }

        public static SoloPanel Get()
        {
            return instance;
        }
    }
}