using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    /// <summary>
    /// Loading panel that appears at the begining of a match, waiting for players to connect
    /// </summary>

    public class LoadPanel : UIPanel
    {
        public Text load_txt;

        private static LoadPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
            if (load_txt != null)
                load_txt.text = "";
        }

        protected override void Start()
        {
            base.Start();

            GameClient.Get().onConnectGame += OnConnect;
            GameClient.Get().onPlayerReady += OnReady;
            GameClient.Get().onGameStart += OnStart;

            SetLoadText("Connecting to server...");
        }

        private void OnConnect()
        {
            SetLoadText("Sending player data...");
        }

        private void OnStart()
        {
            SetLoadText("");
        }

        private void OnReady(int player_id)
        {
            if (player_id == GameClient.Get().GetPlayerID())
            {
                SetLoadText("Waiting for other player...");
            }
        }

        private void SetLoadText(string text)
        {
            if (IsOnline())
            {
                if (load_txt != null)
                    load_txt.text = text;
            }
        }

        public bool IsOnline()
        {
            return GameClient.game_settings.IsOnline();
        }

        public static LoadPanel Get()
        {
            return instance;
        }
    }
}
