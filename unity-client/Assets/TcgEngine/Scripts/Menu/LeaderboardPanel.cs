using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Leaderboard panel contains the ranking of all top players
    /// </summary>

    public class LeaderboardPanel : UIPanel
    {
        public RectTransform content;
        public RankLine line_template;
        public RankLine my_line;
        public float line_spacing = 80f;
        public Text test_text;

        private List<RankLine> lines = new List<RankLine>();

        private static LeaderboardPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
            //lines = scroll_content.GetComponentsInChildren<RankLine>();

            my_line.onClick += OnClickLine;
            InitLines();
        }

        private void OnDestroy()
        {

        }

        private void InitLines()
        {
            for (int i = 0; i < content.transform.childCount; i++)
                Destroy(content.transform.GetChild(i).gameObject);

            int nlines = 100;
            for (int i = 0; i < nlines; i++)
            {
                RankLine line = AddLine(line_template, i);
                lines.Add(line);
            }

            content.sizeDelta = new Vector2(content.sizeDelta.x, nlines * line_spacing + 20f);
        }

        private RankLine AddLine(RankLine template, int index)
        {
            Vector2 pos = Vector2.down * line_spacing;
            GameObject line = Instantiate(template.gameObject, content);
            RectTransform rtrans = line.GetComponent<RectTransform>();
            RankLine rline = line.GetComponent<RankLine>();
            rtrans.anchorMin = new Vector2(0.5f, 1f);
            rtrans.anchorMax = new Vector2(0.5f, 1f);
            rtrans.anchoredPosition = pos + Vector2.down * index * line_spacing;
            rline.onClick += OnClickLine;
            return rline;
        }

        private async void RefreshPanel()
        {
            my_line.Hide();
            foreach (RankLine line in lines)
                line.Hide();

            test_text.enabled = !Authenticator.Get().IsApi();

            if (!Authenticator.Get().IsApi())
                return;

            UserData udata = ApiClient.Get().UserData;

            int index = 0;
            string url = ApiClient.ServerURL + "/users";
            WebResponse res = await ApiClient.Get().SendGetRequest(url);

            UserData[] users = ApiTool.JsonToArray<UserData>(res.data);
            List<UserData> sorted_users = new List<UserData>(users);
            sorted_users.Sort((UserData a, UserData b) => { return b.elo.CompareTo(a.elo); });

            int previous_rank = 0;
            int previous_index = 0;

            foreach (UserData user in sorted_users)
            {
                if (user.permission_level != 1 || user.matches == 0)
                    continue; //Dont show admins and user with no matches

                if (user.username == udata.username)
                {
                    my_line.SetLine(user, index + 1, true);
                }

                if (index < lines.Count)
                {
                    RankLine line = lines[index];
                    int rank_order = (previous_rank == user.elo) ? previous_index : index;
                    line.SetLine(user, rank_order + 1, user.username == udata.username);
                    previous_rank = user.elo;
                    previous_index = rank_order;
                }

                index++;
            }
        }

        private void OnClickLine(string username)
        {

        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshPanel();
        }

        public void OnClickBack()
        {
            Hide();
        }

        public static LeaderboardPanel Get()
        {
            return instance;
        }
    }
}