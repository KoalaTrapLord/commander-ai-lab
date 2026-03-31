using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Text that is displayed at the bottom of the screen when things cant be done
    /// </summary>

    public class WarningText : MonoBehaviour
    {
        public AudioClip warning_audio;
        public Text text;

        private CanvasGroup canvas_group;
        private Animator animator;

        private static WarningText instance;

        void Awake()
        {
            instance = this;
            canvas_group = GetComponent<CanvasGroup>();
            animator = GetComponent<Animator>();
            canvas_group.alpha = 0f;
        }

        void Update()
        {

        }

        public void Show(string txt)
        {
            text.text = txt;
            canvas_group.alpha = 1f;
            animator.SetTrigger("play");
            AudioTool.Get().PlaySFX("warning", warning_audio, 0.7f, false);
        }

        public static void ShowText(string txt)
        {
            WarningText w = WarningText.Get();
            w.Show(txt);
        }

        public static void ShowNotYourTurn()
        {
            ShowText("Not your turn");
        }

        public static void ShowExhausted()
        {
            ShowText("No more action");
        }

        public static void ShowNoMana()
        {
            ShowText("Not enough mana");
        }

        public static void ShowSpellImmune()
        {
            ShowText("Spell Immunity");
        }

        public static void ShowInvalidTarget()
        {
            ShowText("Invalid target");
        }

        public static WarningText Get()
        {
            return instance;
        }
    }
}
