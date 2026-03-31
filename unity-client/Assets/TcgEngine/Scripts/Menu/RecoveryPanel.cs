using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Password recovery panel in the login menu
    /// Only available in API mode
    /// </summary>

    public class RecoveryPanel : UIPanel
    {
        public InputField reset_email;
        public Text reset_error;

        public UIPanel confirm_panel;
        public InputField confirm_code;
        public InputField confirm_password;
        public InputField confirm_pass_confirm;
        public Text confirm_error;

        private static RecoveryPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
        }

        public virtual void RefreshPanel()
        {
            confirm_panel.Hide(true);
            reset_email.text = "";
            confirm_code.text = "";
            confirm_password.text = "";
            confirm_pass_confirm.text = "";
            reset_error.text = "";
            confirm_error.text = "";
        }

        public async void ResetPassword()
        {
            if (ApiClient.Get().IsBusy())
                return;

            reset_error.text = "";

            if (reset_email.text.Length == 0)
                return;

            ResetPasswordRequest req = new ResetPasswordRequest();
            req.email = reset_email.text;

            string url = ApiClient.ServerURL + "/users/password/reset";
            string json = ApiTool.ToJson(req);
            WebResponse res = await ApiClient.Get().SendPostRequest(url, json);
            if (!res.success)
            {
                reset_error.text = res.error;
            }
            else
            {
                confirm_panel.Show();
            }
        }

        public async void ResetPasswordConfirm()
        {
            if (ApiClient.Get().IsBusy())
                return;

            confirm_error.text = "";

            if (confirm_code.text.Length == 0 || confirm_password.text.Length == 0 || confirm_pass_confirm.text.Length == 0)
                return;

            if (confirm_password.text != confirm_pass_confirm.text)
            {
                confirm_error.text = "Passwords don't match";
                return;
            }

            ResetConfirmPasswordRequest req = new ResetConfirmPasswordRequest();
            req.email = reset_email.text;
            req.code = confirm_code.text;
            req.password = confirm_password.text;

            string url = ApiClient.ServerURL + "/users/password/reset/confirm";
            string json = ApiTool.ToJson(req);
            WebResponse res = await ApiClient.Get().SendPostRequest(url, json);
            if (!res.success)
            {
                confirm_error.text = res.error;
            }
            else
            {
                LoginMenu.Get().login_user.text = req.email;
                LoginMenu.Get().login_password.text = "";
                Hide();
            }
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshPanel();
        }

        public override void Hide(bool instant = false)
        {
            base.Hide(instant);
            confirm_panel.Hide();
        }

        public void OnClickReset()
        {
            ResetPassword();
        }

        public void OnClickResetConfirm()
        {
            ResetPasswordConfirm();
        }

        public void OnClickBack()
        {
            Hide();
        }

        public static RecoveryPanel Get()
        {
            return instance;
        }
    }

    [Serializable]
    public class ResetPasswordRequest
    {
        public string email;
    }

    [Serializable]
    public class ResetConfirmPasswordRequest
    {
        public string email;
        public string code;
        public string password;
    }
}
