using TcgEngine.Client;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Endgame panel is shown when a game end
    /// Showing winner and rewards obtained
    /// </summary>

    public class EndGamePanel : UIPanel
    {
        public Text winner_text;
        public Image winner_glow;

        public Text player_name;
        public Text other_name;
        public Image player_avatar;
        public Image other_avatar;

        public Text coins_text;
        public Text xp_text;

        private bool reward_loaded = false;
        private float timer = 0f;

        private int target_coins = 0;
        private int target_xp = 0;
        private float coins = 0;
        private float xp = 0;

        private static EndGamePanel _instance;

        protected override void Awake()
        {
            base.Awake();
            _instance = this;
        }

        protected override void Start()
        {
            base.Start();

            coins_text.text = "";
            xp_text.text = "";

        }

        protected override void Update()
        {
            base.Update();

            if (!reward_loaded && IsVisible())
            {
                timer += Time.deltaTime;
                if (timer > 1f)
                {
                    timer = 0f;
                    RefreshRewards();
                }
            }

            if (reward_loaded)
            {
                coins = Mathf.MoveTowards(coins, target_coins, 2000f * Time.deltaTime);
                xp = Mathf.MoveTowards(xp, target_xp, 500f * Time.deltaTime);

                coins_text.text = "+ " + Mathf.RoundToInt(coins) + " coins";
                xp_text.text = "+ " + Mathf.RoundToInt(xp) + " xp";

                if (Mathf.RoundToInt(coins) == 0)
                    coins_text.text = "";
                if (Mathf.RoundToInt(xp) == 0)
                    xp_text.text = "";
            }
        }

        private void RefreshPanel(int winner)
        {
            Game data = GameClient.Get().GetGameData();
            Player pwinner = data.GetPlayer(winner);
            Player player = GameClient.Get().GetPlayer();
            Player oplayer = GameClient.Get().GetOpponentPlayer();

            player_name.text = player.username;
            other_name.text = oplayer.username;

            AvatarData avat1 = AvatarData.Get(player.avatar);
            AvatarData avat2 = AvatarData.Get(oplayer.avatar);
            if(avat1 != null)
                player_avatar.sprite = avat1.avatar;
            if (avat2 != null)
                other_avatar.sprite = avat2.avatar;

            if (pwinner != null && pwinner == player)
                winner_text.text = "Victory";
            else if (pwinner != null)
                winner_text.text = "Defeat";
            else
                winner_text.text = "Tie";

            if (pwinner == player)
                winner_glow.rectTransform.anchoredPosition = player_avatar.rectTransform.anchoredPosition;
            if (pwinner == oplayer)
                winner_glow.rectTransform.anchoredPosition = other_avatar.rectTransform.anchoredPosition;
            winner_glow.gameObject.SetActive(pwinner != null);
        }

        private async void RefreshRewards()
        {
            //Online rewards
            if (GameClient.game_settings.IsOnline())
            {
                string url = ApiClient.ServerURL + "/matches/" + GameClient.game_settings.game_uid;
                WebResponse res = await ApiClient.Get().SendGetRequest(url);
                if (res.success)
                {
                    reward_loaded = true;
                    MatchResponse match = ApiTool.JsonToObject<MatchResponse>(res.data);
                    string username = ApiClient.Get().Username.ToLower();
                    foreach (MatchDataResponse data in match.udata)
                    {
                        if (data.username.ToLower() == username)
                        {
                            target_coins = data.reward.coins;
                            target_xp = data.reward.xp;
                        }
                    }
                }
            }

            //Adventure Rewards
            if (GameClient.game_settings.game_type == GameType.Adventure)
            {
                LevelData lvl = LevelData.Get(GameClient.game_settings.level);
                if (lvl != null && RewardManager.Get().IsRewardGained())
                {
                    target_coins = lvl.reward_coins;
                    target_xp = lvl.reward_xp;
                    reward_loaded = true;
                }
            }
        }

        public void ShowEnd(int winner)
        {
            reward_loaded = false;
            RefreshPanel(winner);
            RefreshRewards();
            Show();
        }

        public void OnClickQuit()
        {
            GameUI.Get().OnClickQuit();
        }

        public static EndGamePanel Get()
        {
            return _instance;
        }
    }
}
