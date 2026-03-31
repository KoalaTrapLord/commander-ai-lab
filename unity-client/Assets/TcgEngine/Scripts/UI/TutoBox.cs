using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    public class TutoBox : MonoBehaviour
    {
        [Header("UI")]
        public Button next_btn;

        void Awake()
        {

        }

        public void SetNextButton(bool active)
        {
            next_btn.gameObject.SetActive(active);
        }

        public void OnClickNext()
        {
            Tutorial.Get().ShowNext();
        }
    }

}
