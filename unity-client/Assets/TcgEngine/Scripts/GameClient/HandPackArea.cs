using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using TcgEngine.UI;

namespace TcgEngine.Client
{
    /// <summary>
    /// Area of the hand of packs, will spawn/despawns visual packs based on what player has in the data
    /// </summary>

    public class HandPackArea : MonoBehaviour
    {
        public RectTransform hand_area;
        public GameObject pack_template;
        public float card_spacing = 100f;
        public float card_angle = 10f;
        public float card_offset_y = 10f;

        private List<HandPack> packs = new List<HandPack>();

        private Vector3 start_pos;
        private bool is_dragging;
        private bool is_locked;
        private string last_destroyed;
        private float last_destroyed_timer = 0f;

        private static HandPackArea _instance;

        void Awake()
        {
            _instance = this;
        }

        private void Start()
        {
            pack_template.SetActive(false);
            start_pos = hand_area.anchoredPosition;

            if (Authenticator.Get().IsConnected())
                LoadPacks();
            else
                RefreshLogin();
        }

        private async void RefreshLogin()
        {
            bool success = await Authenticator.Get().RefreshLogin();
            if (success)
                LoadPacks();
            else
                SceneNav.GoTo("LoginMenu");
        }

        public async void LoadPacks()
        {
            UserData udata = await Authenticator.Get().LoadUserData();
            if (udata != null)
            {
                RefreshPacks();
            }
        }

        public void RefreshPacks()
        {
            UserData udata = Authenticator.Get().UserData;

            foreach (UserCardData pack in udata.packs)
            {
                PackData dpack = PackData.Get(pack.tid);
                if (dpack != null && !HasPack(pack.tid))
                    SpawnNewPack(pack);
            }

            //Remove removed cards
            for (int i = packs.Count - 1; i >= 0; i--)
            {
                HandPack pack = packs[i];
                if (pack == null || !udata.HasPack(pack.GetPackTid()))
                {
                    packs.RemoveAt(i);
                    if (pack)
                        pack.Remove();
                }
            }
        }

        void Update()
        {
            last_destroyed_timer += Time.deltaTime;

            //Position
            Vector3 tpos = is_locked ? (start_pos + Vector3.down * 200f) : start_pos;
            hand_area.anchoredPosition = Vector3.MoveTowards(hand_area.anchoredPosition, tpos, 200f * Time.deltaTime);

            //Set card index
            int index = 0;
            float count_half = packs.Count / 2f;
            foreach (HandPack card in packs)
            {
                card.deck_position = new Vector2((index - count_half) * card_spacing, (index - count_half) * (index - count_half) * -card_offset_y);
                card.deck_angle = (index - count_half) * -card_angle;
                index++;
            }

            //Set target forcus
            HandPack drag_pack = HandPack.GetDrag();
            is_dragging = drag_pack != null;
        }

        public void SpawnNewPack(UserCardData pack)
        {
            GameObject card_obj = Instantiate(pack_template, hand_area.transform);
            card_obj.SetActive(true);
            card_obj.GetComponent<HandPack>().SetPack(pack);
            card_obj.GetComponent<RectTransform>().anchoredPosition = new Vector2(0f, -100f);
            packs.Add(card_obj.GetComponent<HandPack>());
        }

        public void DelayRefresh(Card card)
        {
            last_destroyed_timer = 0f;
            last_destroyed = card.uid;
        }

        public void Lock(bool locked)
        {
            is_locked = locked;
        }

        public void SortCards()
        {
            packs.Sort(SortFunc);

            int i = 0;
            foreach (HandPack acard in packs)
            {
                acard.transform.SetSiblingIndex(i);
                i++;
            }
        }

        private int SortFunc(HandPack a, HandPack b)
        {
            return a.transform.position.x.CompareTo(b.transform.position.x);
        }

        public bool HasPack(string pack_tid)
        {
            HandPack card = HandPack.Get(pack_tid);
            bool just_destroyed = pack_tid == last_destroyed && last_destroyed_timer < 0.5f;
            return card != null || just_destroyed;
        }

        public bool IsDragging()
        {
            return is_dragging;
        }

        public bool IsLocked()
        {
            return is_locked;
        }

        public static HandPackArea Get()
        {
            return _instance;
        }
    }
}