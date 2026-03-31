using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TcgEngine.UI
{

    /// <summary>
    /// One friend in the friend panel
    /// displays avatar, username and has buttons to interact with the friend
    /// </summary>

    public class FriendLine : MonoBehaviour
    {
        public Text username;
        public Image avatar;

        public Image online_img;
        public Sprite online_sprite;
        public Sprite offline_sprite;
        public Button accept_btn;
        public Button reject_btn;
        public Button watch_btn;
        public Button challenge_btn;

        public UnityAction<FriendLine> onClick;
        public UnityAction<FriendLine> onClickAccept;
        public UnityAction<FriendLine> onClickReject;
        public UnityAction<FriendLine> onClickWatch;
        public UnityAction<FriendLine> onClickChallenge;

        private FriendData fdata;
        private Sprite default_avat;

        private void Awake()
        {
            default_avat = avatar.sprite;

            if (accept_btn != null)
                accept_btn.onClick.AddListener(() => { onClickAccept?.Invoke(this); });
            if (reject_btn != null)
                reject_btn.onClick.AddListener(() => { onClickReject?.Invoke(this); });
            if (watch_btn != null)
                watch_btn.onClick.AddListener(() => { onClickWatch?.Invoke(this); });
            if (challenge_btn != null)
                challenge_btn.onClick.AddListener(() => { onClickChallenge?.Invoke(this); });
        }

        public void SetLine(FriendData user, bool online, bool is_request = false)
        {
            fdata = user;
            username.text = user.username;
            avatar.sprite = default_avat;

            if (avatar != null)
            {
                AvatarData avat = AvatarData.Get(user.avatar);
                if (avat != null)
                    avatar.sprite = avat.avatar;
            }

            if (online_img != null)
            {
                online_img.sprite = online ? online_sprite : offline_sprite;
            }

            if (watch_btn != null)
                watch_btn.gameObject.SetActive(online && !is_request);
            if (challenge_btn != null)
                challenge_btn.gameObject.SetActive(online && !is_request);

            if (accept_btn != null)
                accept_btn.gameObject.SetActive(is_request);
            if (reject_btn != null)
                reject_btn.gameObject.SetActive(is_request);

            gameObject.SetActive(true);
        }

        public void Hide()
        {
            gameObject.SetActive(false);
        }

        public void OnClick()
        {
            onClick?.Invoke(this);
        }

        public FriendData GetFriend()
        {
            return fdata;
        }
    }
}
