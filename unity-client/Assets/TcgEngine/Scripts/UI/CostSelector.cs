using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    /// <summary>
    /// The choice selector is a box that appears when using an ability with ChoiceSelector as target
    /// it let you choose between different abilities
    /// </summary>

    public class CostSelector : SelectorPanel
    {
        public NumberSelector selector;

        private Card caster;

        private static CostSelector instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
        }

        protected override void Start()
        {
            base.Start();

        }

        protected override void Update()
        {
            base.Update();

            Game game = GameClient.Get().GetGameData();
            if (game != null && game.selector == SelectorType.None)
                Hide();
        }

        public void RefreshPanel()
        {
            if (caster == null)
                return;

            Game game = GameClient.Get().GetGameData();
            Player player = game.GetPlayer(caster.player_id);
            selector.SetMax(player.mana);
            selector.SetValue(0);
        }

        public void OnClickOK()
        {
            Game data = GameClient.Get().GetGameData();
            if (data.selector == SelectorType.SelectorCost)
            {
                GameClient.Get().SelectCost(selector.value);
            }

            Hide();
        }

        public void OnClickCancel()
        {
            GameClient.Get().CancelSelection();
            Hide();
        }

        public override void Show(AbilityData iability, Card caster)
        {
            this.caster = caster;
            Show();
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshPanel();
        }

        public override bool ShouldShow()
        {
            Game data = GameClient.Get().GetGameData();
            int player_id = GameClient.Get().GetPlayerID();
            return data.selector == SelectorType.SelectorCost && data.selector_player_id == player_id;
        }

        public static CostSelector Get()
        {
            return instance;
        }
    }
}
