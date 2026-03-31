using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// One line in the LeaderboardPanel
    /// </summary>

    public class RankLine : MonoBehaviour
    {
        public Text ranking;
        public Text player;
        public Text elo_txt;
        public Text winrate_txt;
        public Image highlight;

        public UnityAction<string> onClick;

        private string username;

        void Start()
        {
            highlight.enabled = false;
        }

        public void SetLine(UserData udata, int ranking, bool highlight)
        {
            this.username = udata.username;
            this.ranking.text = ranking.ToString();
            this.player.text = username;
            this.elo_txt.text = udata.elo.ToString();

            int win_rate = Mathf.RoundToInt(udata.victories * 100f / Mathf.Max(udata.matches, 1));
            this.winrate_txt.text = win_rate.ToString() + "%";

            this.highlight.enabled = highlight;
            gameObject.SetActive(true);
        }

        public void Hide()
        {
            gameObject.SetActive(false);
        }

        public string GetUsername()
        {
            return username;
        }

        public void OnClick()
        {
            onClick?.Invoke(username);
        }
    }
}
