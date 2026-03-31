using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using TcgEngine.FX;
using TcgEngine.Client;

namespace TcgEngine.Client
{
    /// <summary>
    /// Visual representation of a booster pack in hand, for the OpenPack scene
    /// </summary>

    public class HandPack : MonoBehaviour
    {
        public Image pack_sprite;
        public Image pack_glow;
        public Text pack_quantity;

        public float move_speed = 10f;
        public float move_rotate_speed = 4f;
        public float move_max_rotate = 10f;

        [HideInInspector]
        public Vector2 deck_position;
        [HideInInspector]
        public float deck_angle;

        [Header("FX")]
        public GameObject pack_open_fx;
        public AudioClip pack_open_audio;

        private string pack_tid = "";
        private int quantity = 0;

        private RectTransform hand_transform;
        private RectTransform card_transform;
        private Vector3 start_scale;
        private float current_alpha = 0f;
        private Vector3 current_rotate;
        private Vector3 target_rotate;
        private Vector3 prev_pos;

        private bool destroyed = false;
        private float focus_timer = 0f;

        private bool focus = false;
        private bool drag = false;

        private static List<HandPack> pack_list = new List<HandPack>();

        void Awake()
        {
            pack_list.Add(this);
            card_transform = transform.GetComponent<RectTransform>();
            hand_transform = transform.parent.GetComponent<RectTransform>();
            start_scale = transform.localScale;
        }

        private void Start()
        {
            EventTrigger etrigger = GetComponent<EventTrigger>();

            EventTrigger.Entry entry0 = new EventTrigger.Entry();
            entry0.eventID = EventTriggerType.PointerDown;
            entry0.callback.AddListener((data) => { OnPointerDown((PointerEventData)data); });
            etrigger.triggers.Add(entry0);

            EventTrigger.Entry entry1 = new EventTrigger.Entry();
            entry1.eventID = EventTriggerType.PointerUp;
            entry1.callback.AddListener((data) => { OnPointerUp((PointerEventData)data); });
            etrigger.triggers.Add(entry1);

            EventTrigger.Entry entry2 = new EventTrigger.Entry();
            entry2.eventID = EventTriggerType.PointerEnter;
            entry2.callback.AddListener((data) => { OnPointerEnter((PointerEventData)data); });
            etrigger.triggers.Add(entry2);

            EventTrigger.Entry entry3 = new EventTrigger.Entry();
            entry3.eventID = EventTriggerType.PointerExit;
            entry3.callback.AddListener((data) => { OnPointerExit((PointerEventData)data); });
            etrigger.triggers.Add(entry3);
        }

        private void OnDestroy()
        {
            pack_list.Remove(this);
        }

        void Update()
        {
            focus_timer += Time.deltaTime;

            UpdatePosition();
        }

        private void UpdatePosition()
        {
            Vector2 target_position = deck_position;
            Vector3 target_size = start_scale;

            float target_alpha = 1f;
            bool player_dragging = HandPackArea.Get().IsDragging();

            if (focus && focus_timer > 0.5f)
            {
                target_position = deck_position + Vector2.up * 40f;
            }

            if (drag)
            {
                target_position = GetTargetPosition();
                target_size = start_scale * 0.8f;
                Vector3 dir = card_transform.position - prev_pos;
                Vector3 addrot = new Vector3(dir.y * 90f, -dir.x * 90f, 0f);
                target_rotate += addrot * move_rotate_speed * Time.deltaTime;
                target_rotate = new Vector3(Mathf.Clamp(target_rotate.x, -move_max_rotate, move_max_rotate), Mathf.Clamp(target_rotate.y, -move_max_rotate, move_max_rotate), 0f);
                current_rotate = Vector3.Lerp(current_rotate, target_rotate, move_rotate_speed * Time.deltaTime);
                move_speed = 9f;
                target_alpha = 0.8f;
            }
            else
            {
                target_rotate = new Vector3(0f, 0f, deck_angle);
                current_rotate = new Vector3(0f, 0f, deck_angle);
            }

            card_transform.anchoredPosition = Vector2.Lerp(card_transform.anchoredPosition, target_position, Time.deltaTime * move_speed);
            card_transform.rotation = Quaternion.Slerp(card_transform.rotation, Quaternion.Euler(current_rotate), Time.deltaTime * move_speed);
            card_transform.localScale = Vector3.Lerp(card_transform.localScale, target_size, 4f * Time.deltaTime);

            pack_glow.enabled = (focus && !player_dragging) || drag;
            current_alpha = Mathf.MoveTowards(current_alpha, target_alpha, 2f * Time.deltaTime);
            pack_sprite.color = new Color(1f, 1f, 1f, current_alpha);
            pack_glow.color = new Color(pack_glow.color.r, pack_glow.color.g, pack_glow.color.b, current_alpha * 0.8f);
            pack_quantity.text = quantity.ToString();

            prev_pos = Vector3.Lerp(prev_pos, card_transform.position, 1f * Time.deltaTime);
        }

        private Vector2 GetTargetPosition()
        {
            RectTransformUtility.ScreenPointToLocalPointInRectangle(hand_transform, MouseInput.GetMousePosition(), Camera.main, out Vector2 tpos);
            return tpos;
        }

        public void SetPack(UserCardData pack)
        {
            this.pack_tid = pack.tid;
            this.quantity = pack.quantity;

            PackData ipack = PackData.Get(pack.tid);
            if (ipack)
            {
                pack_sprite.sprite = ipack.pack_img;
            }
        }

        public void OpenPack()
        {
            FXTool.DoFX(pack_open_fx, transform.position);
            AudioTool.Get().PlaySFX("pack_open", pack_open_audio);
            Destroy(gameObject);
            OpenPackMenu.Get().OpenPack(pack_tid);
        }

        public void Remove()
        {
            quantity--;
            if (quantity <= 0)
                Kill();
        }

        public void Kill()
        {
            if (!destroyed)
            {
                destroyed = true;
                Destroy(gameObject);
            }
        }

        public bool IsFocus()
        {
            return focus && !drag;
        }

        public bool IsDrag()
        {
            return drag;
        }

        public PackData GetPackData()
        {
            return PackData.Get(pack_tid);
        }

        public string GetPackTid()
        {
            return pack_tid;
        }

        public int GetPackQuantity()
        {
            UserData udata = Authenticator.Get().UserData;
            return udata.GetPackQuantity(pack_tid);
        }

        private void OnPointerEnter(PointerEventData edata)
        {
            if (HandPackArea.Get().IsLocked())
                return;

            focus = true;
        }

        private void OnPointerExit(PointerEventData edata)
        {
            focus = false;
            focus_timer = 0f;
        }

        private void OnPointerDown(PointerEventData edata)
        {
            if (HandPackArea.Get().IsLocked())
                return;

            drag = true;
            AudioTool.Get().PlaySFX("hand_card", AssetData.Get().hand_card_click_audio);
        }

        private void OnPointerUp(PointerEventData edata)
        {
            Vector3 world_pos = MouseToWorld(MouseInput.GetMousePosition());
            if (drag && world_pos.y > -2.5f)
                OpenPack();
            else
                HandPackArea.Get().SortCards();
            drag = false;
        }

        public Vector3 MouseToWorld(Vector3 mouse_pos)
        {
            Vector3 wpos = Camera.main.ScreenToWorldPoint(mouse_pos);
            wpos.z = 0f;
            return wpos;
        }

        public PackData PackData { get { return GetPackData(); } }

        public static HandPack GetDrag()
        {
            foreach (HandPack card in pack_list)
            {
                if (card.IsDrag())
                    return card;
            }
            return null;
        }

        public static HandPack GetFocus()
        {
            foreach (HandPack card in pack_list)
            {
                if (card.IsFocus())
                    return card;
            }
            return null;
        }

        public static HandPack Get(string uid)
        {
            foreach (HandPack card in pack_list)
            {
                if (card && card.GetPackTid() == uid)
                    return card;
            }
            return null;
        }

        public static List<HandPack> GetAll()
        {
            return pack_list;
        }
    }
}
