using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{

    public class JoinCodePanel : UIPanel
    {
        public InputField code_field;

        private string game_code = "";

        private static JoinCodePanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
        }

        protected override void Update()
        {
            base.Update();
        }


        public void OnClickRandomize()
        {
            game_code = GameTool.GenerateRandomID(4,6).ToUpper();
            code_field.text = game_code;
        }

        public void OnClickJoinCode()
        {
            if (code_field.text.Length < 3)
                return;

            game_code = code_field.text.ToUpper();
            MainMenu.Get().StartMathmaking(GameMode.Casual, "code_" + game_code);
            Hide();
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            code_field.text = "";
        }

        public string GetCode()
        {
            return game_code;
        }

        public static JoinCodePanel Get()
        {
            return instance;
        }

    }
}
