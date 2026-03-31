using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Box that appears when using the SelectTarget ability target
    /// </summary>

    public class SelectTargetUI : SelectorPanel
    {
        public Text title;
        public Text desc;

        private static SelectTargetUI _instance;

        protected override void Awake()
        {
            _instance = this;
            base.Awake();
        }

        protected override void Update()
        {
            base.Update();

            Game game = GameClient.Get().GetGameData();
            if (game != null && game.selector == SelectorType.None)
                Hide();
        }

        public override void Show(AbilityData ability, Card caster)
        {
            this.title.text = ability.title;
            //this.desc.text = ability.desc;
            Show();
        }

        public void OnClickClose()
        {
            GameClient.Get().CancelSelection();
        }

        public override bool ShouldShow()
        {
            Game data = GameClient.Get().GetGameData();
            int player_id = GameClient.Get().GetPlayerID();
            return data.selector == SelectorType.SelectTarget && data.selector_player_id == player_id;
        }

        public static SelectTargetUI Get()
        {
            return _instance;
        }
    }
}