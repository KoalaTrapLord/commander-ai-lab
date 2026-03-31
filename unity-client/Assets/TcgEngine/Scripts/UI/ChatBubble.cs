using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// UI that appears when sending a chat message
    /// </summary>

    public class ChatBubble : MonoBehaviour
    {
        public Text msg_txt;
        public Image bubble;
        public CanvasGroup group;

        private float timer = 0f;

        void Start()
        {

        }

        private void Update()
        {
            timer -= Time.deltaTime;
            group.alpha = timer;

            if (timer < 0f)
                Hide();
        }

        public void SetLine(string msg, float duration)
        {
            msg_txt.text = msg;
            timer = duration;
            gameObject.SetActive(true);
        }

        public void Hide()
        {
            gameObject.SetActive(false);
        }
    }
}