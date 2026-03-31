using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    /// <summary>
    /// Player panel appears when you click on your avatar in the menu
    /// it shows all stats related to your account, and let you change avatar/cardback
    /// </summary>

    public class PlayerPanel : UIPanel
    {
        [Header("Player")]
        public Text player_name;
        public Text player_level;
        public AvatarUI avatar;
        public CardbackUI cardback;
        public Text elo;
        public Text winrate;
        public Text cards_all;
        public Text victories;
        public Text defeats;

        [Header("Bottom bar")]
        public GameObject buttons_area;
        public GameObject account_button;
        public GameObject sell_button;

        [Header("Avatars")]
        public UIPanel avatar_panel;
        public AvatarUI[] avatars;

        [Header("Cardbacks")]
        public UIPanel cardback_panel;
        public CardbackUI[] cardbacks;

        [Header("Edit Panel")]
        public UIPanel edit_panel;
        public InputField user_email;
        public InputField user_password_prev;
        public InputField user_password_new;
        public InputField user_password_confirm;
        public Button edit_change_email;
        public Button edit_change_password;
        public Button resend_button;
        public Button confirm_button;
        public Text edit_error;

        private string username;
        private UserData user_data;

        private static PlayerPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;

            foreach (AvatarUI icon in avatars)
                icon.onClick += OnClickAvatar;

            foreach (CardbackUI icon in cardbacks)
                icon.onClick += OnClickCardback;
        }

        protected override void Update()
        {
            base.Update();

        }

        protected override void Start()
        {
            base.Start();
        }

        private async void LoadData()
        {
            if (IsYou())
                user_data = Authenticator.Get().UserData;
            else
                user_data = await ApiClient.Get().LoadUserData(username);

            RefreshPanel();
        }

        private void ClearPanel()
        {
            player_name.text = "";
            elo.text = "";
            winrate.text = "";
            player_level.text = "";
            avatar.Hide();
            cardback.Hide();
        }

        private void RefreshPanel()
        {
            avatar_panel.Hide();
            //cardback_panel.Hide();

            if (user_data != null)
            {
                UserData user = user_data;
                player_name.text = user.username;
                player_level.text = GameplayData.Get().GetPlayerLevel(user.xp).ToString();

                AvatarData avatar = AvatarData.Get(user.avatar);
                this.avatar.SetAvatar(avatar);

                CardbackData cb = CardbackData.Get(user.cardback);
                this.cardback.SetCardback(cb);

                int winrate_val = user.matches > 0 ? Mathf.RoundToInt(user.victories * 100f / user.matches) : 0;
                winrate.text = winrate_val + "%";
                elo.text = user.elo.ToString();
                victories.text = user.victories.ToString();
                defeats.text = user.defeats.ToString();
                cards_all.text = user.CountUniqueCards() + " / " + CardData.GetAllDeckbuilding().Count;

                buttons_area?.SetActive(IsYou());    //Buttons like logout only active if your account
                account_button?.SetActive(Authenticator.Get().IsApi());
                sell_button?.SetActive(Authenticator.Get().IsApi());
            }
        }

        private void RefreshAvatarList()
        {
            foreach (AvatarUI icon in avatars)
                icon.SetDefaultAvatar();

            int index = 0;
            foreach (AvatarData adata in AvatarData.GetAll())
            {
                if (index < avatars.Length)
                {
                    AvatarUI line = avatars[index];
                    if (adata != null)
                    {
                        line.SetAvatar(adata);
                        index++;
                    }
                }
            }
        }

        private void RefreshCardBackList()
        {
            foreach (CardbackUI line in cardbacks)
                line.Hide();

            int index = 0;
            foreach (CardbackData cbdata in CardbackData.GetAll())
            {
                if (index < cardbacks.Length)
                {
                    CardbackUI line = cardbacks[index];
                    if (cbdata != null)
                    {
                        line.SetCardback(cbdata);
                        index++;
                    }
                }
            }
        }

        private void OnClickAvatar(AvatarData avatar)
        {
            user_data = Authenticator.Get().UserData;
            if (avatar != null && user_data != null && IsYou())
            {
                user_data.avatar = avatar.id;
                RefreshPanel();
                SaveUserAvatar(avatar);
                avatar_panel.Hide();
            }
        }

        private void OnClickCardback(CardbackData cb)
        {
            user_data = Authenticator.Get().UserData;
            if (cb != null && user_data != null && IsYou())
            {
                user_data.cardback = cb.id;
                RefreshPanel();
                SaveUserCardback(cb);
                cardback_panel.Hide();
            }
        }

        private async void SaveUserAvatar(AvatarData avatar)
        {
            if (ApiClient.Get().IsConnected())
            {
                string url = ApiClient.ServerURL + "/users/edit/" + ApiClient.Get().UserID;
                EditUserRequest req = new EditUserRequest();
                req.avatar = avatar.id;
                string json_data = ApiTool.ToJson(req);
                await ApiClient.Get().SendRequest(url, "POST", json_data);
            }
            await Authenticator.Get().SaveUserData();
            MainMenu.Get().RefreshUserData();
            RefreshPanel();
        }

        private async void SaveUserCardback(CardbackData cardback)
        {
            if (ApiClient.Get().IsConnected())
            {
                string url = ApiClient.ServerURL + "/users/edit/" + ApiClient.Get().UserID;
                EditUserRequest req = new EditUserRequest();
                req.cardback = cardback.id;
                string json_data = ApiTool.ToJson(req);
                await ApiClient.Get().SendRequest(url, "POST", json_data);
            }
            await Authenticator.Get().SaveUserData();
            MainMenu.Get().RefreshUserData();
            RefreshPanel();
        }

        public void OnClickAvatar()
        {
            if (!IsYou())
                return;

            RefreshAvatarList();
            avatar_panel.Show();
        }

        public void OnClickCardBack()
        {
            if (!IsYou())
                return;

            RefreshCardBackList();
            cardback_panel.Show();
        }

        public void OnClickFriends()
        {
            FriendPanel.Get().Show();
        }

        public void OnClickDuplicates()
        {
            SellDuplicatePanel.Get().Show();
        }

        public void OnClickEdit()
        {
            user_email.readOnly = true;
            user_password_prev.readOnly = true;
            user_password_new.readOnly = true;
            user_password_confirm.readOnly = true;
            user_password_new.gameObject.SetActive(false);
            user_password_confirm.gameObject.SetActive(false);

            UserData udata = Authenticator.Get().UserData;
            user_email.text = udata.email;
            user_password_prev.text = "password";
            user_password_new.text = "password";
            user_password_confirm.text = "password";
            edit_change_email.gameObject.SetActive(true);
            edit_change_password.gameObject.SetActive(true);
            resend_button.gameObject.SetActive(udata.validation_level == 0);
            confirm_button.gameObject.SetActive(false);
            edit_error.text = "";
            edit_panel.Show();
        }

        public void OnClickChangePass()
        {
            OnClickEdit();
            user_password_prev.readOnly = false;
            user_password_new.readOnly = false;
            user_password_confirm.readOnly = false;
            user_password_prev.text = "";
            user_password_new.text = "";
            user_password_confirm.text = "";
            user_password_new.gameObject.SetActive(true);
            user_password_confirm.gameObject.SetActive(true);
            edit_change_email.gameObject.SetActive(false);
            edit_change_password.gameObject.SetActive(false);
            resend_button.gameObject.SetActive(false);
            confirm_button.gameObject.SetActive(true);
            user_password_prev.Select();
        }

        public void OnClickChangeEmail()
        {
            OnClickEdit();
            user_email.readOnly = false;
            edit_change_email.gameObject.SetActive(false);
            edit_change_password.gameObject.SetActive(false);
            resend_button.gameObject.SetActive(false);
            confirm_button.gameObject.SetActive(true);
            user_email.Select();
        }

        public async void OnClickResendConfirm()
        {
            edit_error.text = "";
            string url = ApiClient.ServerURL + "/users/email/resend";
            WebResponse res = await ApiClient.Get().SendPostRequest(url, "");
            if (res.success)
            {
                edit_panel.Hide();
            }
            else
            {
                edit_error.text = res.error;
            }
        }

        public async void OnClickEditConfirm()
        {
            edit_error.text = "";

            if (!user_email.readOnly && user_email.text.Length > 0)
            {
                EditEmailRequest req = new EditEmailRequest();
                req.email = user_email.text;
                string url = ApiClient.ServerURL + "/users/email/edit/";
                string json = ApiTool.ToJson(req);
                WebResponse res = await ApiClient.Get().SendPostRequest(url, json);
                if (res.success)
                {
                    edit_panel.Hide();
                    MainMenu.Get().RefreshUserData();
                }
                else
                {
                    edit_error.text = res.error;
                }
            }
            else if (!user_password_new.readOnly && user_password_new.text.Length > 0)
            {
                if (user_password_new.text == user_password_confirm.text)
                {
                    EditPasswordRequest req = new EditPasswordRequest();
                    req.password_previous = user_password_prev.text;
                    req.password_new = user_password_new.text;
                    string url = ApiClient.ServerURL + "/users/password/edit/";
                    string json = ApiTool.ToJson(req);
                    WebResponse res = await ApiClient.Get().SendPostRequest(url, json);
                    if (res.success)
                    {
                        edit_panel.Hide();
                    }
                    else
                    {
                        edit_error.text = res.error;
                    }
                }
            }
        }

        public bool IsYou()
        {
            return username == ApiClient.Get().Username;
        }

        public void ShowPlayer()
        {
            string user = ApiClient.Get().Username;
            ShowPlayer(user);
        }

        public void ShowPlayer(string user)
        {
            if (username != user)
                ClearPanel();
            username = user;
            LoadData();
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            ShowPlayer();
        }

        public override void Hide(bool instant = false)
        {
            base.Hide(instant);
            edit_panel.Hide();
        }

        public static PlayerPanel Get()
        {
            return instance;
        }
    }
}
