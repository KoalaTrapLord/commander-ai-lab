using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using TcgEngine;
using UnityEngine.EventSystems;

namespace TcgEngine.UI
{
    /// <summary>
    /// Display a pack and all its information
    /// </summary>

    public class PackUI : MonoBehaviour, IPointerClickHandler
    {
        public Image pack_img;
        public Text pack_title;
        public Text pack_quantity;
        public Image quantity_bar;

        public UnityAction<PackUI> onClick;
        public UnityAction<PackUI> onClickRight;

        private PackData pack;

        void Awake()
        {

        }

        public void SetPack(PackData pack)
        {
            this.pack = pack;

            if (pack != null)
            {
                if (pack_title != null)
                {
                    pack_title.enabled = true;
                    pack_title.text = pack.title;
                }
                pack_img.enabled = true;
                pack_img.sprite = pack.pack_img;
            }

            if (pack_quantity != null)
                pack_quantity.enabled = false;
            if (quantity_bar != null)
                quantity_bar.enabled = false;
        }

        public void SetPack(PackData pack, int quantity)
        {
            SetPack(pack);

            if (pack_quantity != null)
            {
                pack_quantity.enabled = quantity > 0;
                pack_quantity.text = quantity.ToString();
            }

            if (quantity_bar != null)
                quantity_bar.enabled = quantity > 0;
        }

        public void Hide()
        {
            this.pack = null;
            pack_img.enabled = false;
            if(pack_title != null)
                pack_title.enabled = false;
            if (pack_quantity != null)
                pack_quantity.enabled = false;
            if (quantity_bar != null)
                quantity_bar.enabled = false;
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            if (eventData.button == PointerEventData.InputButton.Left)
            {
                if (onClick != null)
                    onClick.Invoke(this);
            }

            if (eventData.button == PointerEventData.InputButton.Right)
            {
                if (onClickRight != null)
                    onClickRight.Invoke(this);
            }
        }

        public PackData GetPack()
        {
            return pack;
        }
    }
}