using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using System.Linq;

namespace TcgEngine.UI
{
    /// <summary>
    /// Main script for the main menu scene
    /// </summary>

    public class MainMenu : MonoBehaviour
    {
        public AudioClip music;
        public AudioClip ambience;

        [Header("Player UI")]
        public Text username_txt;
        public Text credits_txt;
        public AvatarUI avatar;
        public GameObject loader;

        [Header("UI")]
        public Text version_text;
        public DeckSelector deck_selector;
        public DeckDisplay deck_preview;

        private bool starting = false;

        private static MainMenu instance;

        void Awake()
        {
            instance = this;

            //Set default settings
            Application.targetFrameRate = 120;
            GameClient.game_settings = GameSettings.Default;
            GameClient.observe_user = "";
        }

        private void Start()
        {
            BlackPanel.Get().Show(true);
            AudioTool.Get().PlayMusic("music", music);
            AudioTool.Get().PlaySFX("ambience", ambience, 0.5f, true, true);

            username_txt.text = "";
            credits_txt.text = "";
            version_text.text = "Version " + Application.version;
            deck_selector.onChange += OnChangeDeck;

            if (Authenticator.Get().IsConnected())
                AfterLogin();
            else
                RefreshLogin();
        }

        void Update()
        {
            UserData udata = Authenticator.Get().UserData;
            if (udata != null)
            {
                credits_txt.text = GameUI.FormatNumber(udata.coins);
            }

            bool matchmaking = GameClientMatchmaker.Get().IsMatchmaking();
            if (loader.activeSelf != matchmaking)
                loader.SetActive(matchmaking);
            if (MatchmakingPanel.Get().IsVisible() != matchmaking)
                MatchmakingPanel.Get().SetVisible(matchmaking);
        }

        private async void RefreshLogin()
        {
            bool success = await Authenticator.Get().RefreshLogin();
            if (success)
                AfterLogin();
            else
                SceneNav.GoTo("LoginMenu");
        }

        private void AfterLogin()
        {
            BlackPanel.Get().Hide();

            //Events
            GameClientMatchmaker matchmaker = GameClientMatchmaker.Get();
            matchmaker.onMatchmaking += OnMatchmakingDone;
            matchmaker.onMatchList += OnReceiveObserver;

            //Deck
            GameClient.player_settings.deck.tid = PlayerPrefs.GetString("tcg_deck_" + Authenticator.Get().Username, "");

            //UserData
            RefreshUserData();

            //Friend list
            //FriendPanel.Get().Show();
        }

        public async void RefreshUserData()
        {
            UserData user = await Authenticator.Get().LoadUserData();
            if (user != null)
            {
                username_txt.text = user.username;
                credits_txt.text = GameUI.FormatNumber(user.coins);
                
                AvatarData avatar = AvatarData.Get(user.avatar);
                this.avatar.SetAvatar(avatar);

                //Decks
                RefreshDeckList();
            }
        }

        public void RefreshDeckList()
        {
            deck_selector.SetupUserDeckList();
            deck_selector.SelectDeck(GameClient.player_settings.deck.tid);
            RefreshDeck(deck_selector.GetDeckID());
        }

        private void RefreshDeck(string tid)
        {
            if (deck_preview != null)
            {
                deck_preview.SetDeck(tid);
            }
        }

        private void OnChangeDeck(string tid)
        {
            GameClient.player_settings.deck = deck_selector.GetDeck();
            PlayerPrefs.SetString("tcg_deck_" + Authenticator.Get().Username, tid);
            RefreshDeck(tid);
        }

        private void OnMatchmakingDone(MatchmakingResult result)
        {
            if (result == null)
                return;

            if (result.success)
            {
                Debug.Log("Matchmaking found: " + result.success + " " + result.server_url + "/" + result.game_uid);
                StartGame(GameType.Multiplayer, result.game_uid, result.server_url);
            }
            else
            {
                MatchmakingPanel.Get().SetCount(result.players);
            }
        }

        private void OnReceiveObserver(MatchList list)
        {
            MatchListItem target = null;
            foreach (MatchListItem item in list.items)
            {
                if (item.usernames.Contains(GameClient.observe_user))
                    target = item;
            }

            if (target != null)
            {
                StartGame(GameType.Observer, target.game_uid, target.game_url);
            }
        }

        public void StartGame(GameType type, GameMode mode)
        {
            string uid = GameTool.GenerateRandomID();
            GameClient.game_settings.game_type = type;
            GameClient.game_settings.game_mode = mode;
            StartGame(uid); 
        }

        public void StartGame(GameType type, string game_uid, string server_url = "")
        {
            GameClient.game_settings.game_type = type;
            StartGame(game_uid, server_url);
        }

        public void StartGame(string game_uid, string server_url = "")
        {
            if (!starting)
            {
                starting = true;
                GameClient.game_settings.server_url = server_url; //Empty server_url will use the default one in NetworkData
                GameClient.game_settings.game_uid = game_uid;
                FadeToScene(GameClient.game_settings.GetScene());
            }
        }

        public void StartObserve(string user)
        {
            GameClient.observe_user = user;
            GameClientMatchmaker.Get().StopMatchmaking();
            GameClientMatchmaker.Get().RefreshMatchList(user);
        }

        public void StartChallenge(string user)
        {
            string self = Authenticator.Get().Username;
            if (self == user)
                return; //Cant challenge self

            string key;
            if (self.CompareTo(user) > 0)
                key = self + "-" + user;
            else
                key = user + "-" + self;

            StartMathmaking(GameMode.Casual, key);
        }

        public void StartMathmaking(GameMode mode, string group)
        {
            UserDeckData deck = deck_selector.GetDeck();
            if (deck != null)
            {
                GameClient.game_settings.game_type = GameType.Multiplayer;
                GameClient.game_settings.game_mode = mode;
                GameClient.player_settings.deck = deck;
                GameClient.game_settings.scene = GameplayData.Get().GetRandomArena();
                GameClientMatchmaker.Get().StartMatchmaking(group, GameClient.game_settings.nb_players);
            }
        }

        public void OnClickSolo()
        {
            if (!Authenticator.Get().IsConnected())
            {
                FadeToScene("LoginMenu");
                return;
            }

            SoloPanel.Get().Show();
        }

        public void OnClickPvP()
        {
            if (!Authenticator.Get().IsConnected())
            {
                FadeToScene("LoginMenu");
                return;
            }

            UserDeckData deck = deck_selector.GetDeck();
            if (deck == null || !deck.IsValid())
                return;

            StartMathmaking(GameMode.Ranked, "");
        }

        public void OnClickAdventure()
        {
            AdventurePanel.Get().Show();
        }

        public void OnClickPlayCode()
        {
            JoinCodePanel.Get().Show();
        }
        
        public void OnClickCancelMatch()
        {
            GameClientMatchmaker.Get().StopMatchmaking();
            GameClientMatchmaker.Get().Disconnect();
        }

        public void OnClickSettings()
        {
            SettingsPanel.Get().Show();
        }

        public void FadeToScene(string scene)
        {
            StartCoroutine(FadeToRun(scene));
        }

        private IEnumerator FadeToRun(string scene)
        {
            BlackPanel.Get().Show();
            AudioTool.Get().FadeOutMusic("music");
            TcgNetwork.Get().Disconnect();
            yield return new WaitForSeconds(1f);
            SceneNav.GoTo(scene);
        }

        public void OnClickLogout()
        {
            TcgNetwork.Get().Disconnect();
            Authenticator.Get().Logout();
            FadeToScene("LoginMenu");
        }

        public void OnClickQuit()
        {
            Application.Quit();
        }

        public static MainMenu Get()
        {
            return instance;
        }
    }
}
