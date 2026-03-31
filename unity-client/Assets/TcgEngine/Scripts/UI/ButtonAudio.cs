using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Add sound when clicking on a button
    /// </summary>

    public class ButtonAudio : MonoBehaviour
    {
        public AudioClip click_audio;

        void Start()
        {
            Button button = GetComponent<Button>();
            if (button != null)
                button.onClick.AddListener(OnClick);
        }

        void OnClick()
        {
            AudioTool.Get().PlaySFX("ui", click_audio);
        }
    }
}
