using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.InputSystem;

namespace TcgEngine.UI
{
    /// <summary>
    /// Main script for the login menu scene
    /// </summary>

    public class LoginMenu : MonoBehaviour
    {
        [Header("Login")]
        public UIPanel login_panel;
        public InputField login_user;
        public InputField login_password;
        public Button login_button;
        public GameObject login_bottom;
        public Text error_msg;

        [Header("Register")]
        public UIPanel register_panel;
        public InputField register_username;
        public InputField register_email;
        public InputField register_password;
        public InputField register_password_confirm;
        public Button register_button;

        [Header("Other")]
        public GameObject test_area;

        [Header("Music")]
        public AudioClip music;

        private bool clicked = false;

        private static LoginMenu instance;

        void Awake()
        {
            instance = this;
        }

        private void Start()
        {
            AudioTool.Get().PlayMusic("music", music);
            BlackPanel.Get().Show(true);
            error_msg.text = "";
            test_area.SetActive(Authenticator.Get().IsTest());

            string user = PlayerPrefs.GetString("tcg_last_user", "");
            login_user.text = user;

            if (Authenticator.Get().IsTest())
            {
                login_password.gameObject.SetActive(false);
                login_bottom.SetActive(false);
            }
            else if (!string.IsNullOrEmpty(user))
            {
                SelectField(login_password);
            }

            RefreshLogin();
        }

        void Update()
        {
            login_button.interactable = !clicked && !string.IsNullOrWhiteSpace(login_user.text);
            register_button.interactable = !clicked && !string.IsNullOrWhiteSpace(register_username.text) && !string.IsNullOrWhiteSpace(register_email.text)
                && !string.IsNullOrWhiteSpace(register_password.text) && register_password.text == register_password_confirm.text;

            if (login_panel.IsVisible())
            {
                if (KeyInput.IsKeyPress(Key.Tab))
                {
                    if (login_user.isFocused)
                        SelectField(login_password);
                    else
                        SelectField(login_user);
                }

                if (KeyInput.IsKeyPress(Key.Enter))
                {
                    if (login_button.interactable)
                        OnClickLogin();
                }
            }

            if (register_panel.IsVisible())
            {
                if (KeyInput.IsKeyPress(Key.Tab))
                {
                    if (register_username.isFocused)
                        SelectField(register_email);
                    else if (register_email.isFocused)
                        SelectField(register_password);
                    else if (register_password.isFocused)
                        SelectField(register_password_confirm);
                    else
                        SelectField(register_username);
                }

                if (KeyInput.IsKeyPress(Key.Enter))
                {
                    if (register_button.interactable)
                        OnClickRegister();
                }
            }
        }

        private async void RefreshLogin()
        {
            bool success = await Authenticator.Get().RefreshLogin();
            if (success)
            {
                SceneNav.GoTo("Menu");
            }
            else
            {
                login_panel.Show();
                BlackPanel.Get().Hide();
            }
        }

        private async void Login(string user, string password)
        {
            clicked = true;
            error_msg.text = "";

            bool success = await Authenticator.Get().Login(user, password);
            if (success)
            {
                PlayerPrefs.SetString("tcg_last_user", login_user.text);
                FadeToScene("Menu");
            }
            else
            {
                clicked = false;
                error_msg.text = Authenticator.Get().GetError();
            }
        }

        private async void Register(string email, string user, string password)
        {
            clicked = true;
            error_msg.text = "";

            bool success = await Authenticator.Get().Register(register_email.text, register_username.text, register_password.text);
            if (success)
            {
                login_user.text = register_username.text;
                login_password.text = register_password.text;
                login_panel.Show();
                register_panel.Hide();
            }
            else
            {
                error_msg.text = Authenticator.Get().GetError();
            }
            clicked = false;
        }

        public void OnClickLogin()
        {
            if (string.IsNullOrWhiteSpace(login_user.text))
                return;
            if (clicked)
                return;

            Login(login_user.text, login_password.text);
        }

        public void OnClickRegister()
        {
            if (string.IsNullOrWhiteSpace(register_username.text))
                return;
            if (string.IsNullOrWhiteSpace(register_email.text))
                return;

            if (register_password.text != register_password_confirm.text)
                return;

            if (clicked)
                return;

            Register(register_email.text, register_username.text, register_password.text);
        }

        public void OnClickSwitchLogin()
        {
            login_panel.Show();
            register_panel.Hide();
            login_user.text = "";
            login_password.text = "";
            error_msg.text = "";
            SelectField(login_user);
        }

        public void OnClickSwitchRegister()
        {
            login_panel.Hide();
            register_panel.Show();
            error_msg.text = "";
            SelectField(register_username);
        }

        public void OnClickSwitchReset()
        {
            RecoveryPanel.Get().Show();
        }

        public void OnClickGo()
        {
            FadeToScene("Menu");
        }

        public void OnClickQuit()
        {
            Application.Quit();
        }

        private void SelectField(InputField field)
        {
            if (!GameTool.IsMobile())
                field.Select();
        }

        public void FadeToScene(string scene)
        {
            StartCoroutine(FadeToRun(scene));
        }

        private IEnumerator FadeToRun(string scene)
        {
            BlackPanel.Get().Show();
            AudioTool.Get().FadeOutMusic("music");
            yield return new WaitForSeconds(1f);
            SceneNav.GoTo(scene);
        }

        public static LoginMenu Get()
        {
            return instance;
        }
    }
}