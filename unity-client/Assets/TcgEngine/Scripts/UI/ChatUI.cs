using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.InputSystem;
using TcgEngine.Client;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Chat area in the UI, 
    /// its where you can write chat msg and will display chat message received from the server
    /// </summary>

    public class ChatUI : MonoBehaviour
    {
        public bool is_opponent;

        [Header("Display Box")]
        public ChatBubble chat_bubble;
        public AudioClip chat_audio;

        [Header("Write Box")]
        public UIPanel chat_field_area;
        public InputField chat_field;

        private string chat_msg;
        private float chat_timer = 0f;

        private static List<ChatUI> ui_list = new List<ChatUI>();

        private void Awake()
        {
            ui_list.Add(this);
        }

        private void OnDestroy()
        {
            ui_list.Remove(this);
        }

        void Start()
        {
            GameClient.Get().onChatMsg += OnChat;
            RefreshChat();
        }

        void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            int player_id = is_opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
            Game data = GameClient.Get().GetGameData();
            Player player = data.GetPlayer(player_id);

            if (player != null)
            {
                //Chat
                if (chat_field_area != null && !is_opponent && KeyInput.IsKeyPress(Key.Enter))
                {
                    if (chat_field_area.IsVisible())
                    {
                        if (!string.IsNullOrWhiteSpace(chat_field.text))
                            SendChat(chat_field.text);
                        chat_field.text = "";
                        chat_field_area.Hide();
                        GUI.FocusControl(null);
                    }
                    else
                    {
                        chat_field_area.Show();
                    }

                    chat_field.ActivateInputField();
                    chat_field.Select();
                }

                //Chat remove
                chat_timer += Time.deltaTime;
                if (chat_timer > 5f)
                    chat_msg = null;
            }
        }

        private void SendChat(string msg)
        {
            GameClient.Get().SendChatMsg(msg);
        }

        private void RefreshChat()
        {
            chat_bubble.Hide();

            if(!string.IsNullOrWhiteSpace(chat_msg))
                chat_bubble.SetLine(chat_msg, 5f);
        }

        private void OnChat(int chat_player_id, string msg)
        {
            int player_id = is_opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
            if (player_id == chat_player_id)
            {
                chat_msg = msg;
                chat_timer = 0f;
                AudioTool.Get().PlaySFX("chat", chat_audio);
                RefreshChat();
            }
        }

        public void OnClickSend()
        {
            if (chat_field_area != null && !string.IsNullOrWhiteSpace(chat_field.text))
            {
                SendChat(chat_field.text);
                chat_field.text = "";
                chat_field_area.Hide();
                GUI.FocusControl(null);
            }
        }

        public static ChatUI Get(bool opponent)
        {
            foreach (ChatUI ui in ui_list)
            {
                if (ui.is_opponent == opponent)
                    return ui;
            }
            return null;
        }

    }
}