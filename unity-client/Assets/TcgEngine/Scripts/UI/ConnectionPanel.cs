using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    /// <summary>
    /// Panel that appears when internet connection is lost
    /// </summary>

    public class ConnectionPanel : UIPanel
    {
        private static ConnectionPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
        }

        public void OnClickQuit()
        {
            GameClient.Get()?.Disconnect();
            SceneNav.GoTo("LoginMenu");
        }

        public static ConnectionPanel Get()
        {
            return instance;
        }
    }
}
