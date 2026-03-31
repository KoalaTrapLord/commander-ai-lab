using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Class that let you store a ID with each element of a Dropdown
    /// </summary>

    [System.Serializable]
    public class DropdownValueItem
    {
        public string id;
        public string text;
    }

    [RequireComponent(typeof(Dropdown))]
    public class DropdownValue : MonoBehaviour
    {
        public UnityAction<int, string> onValueChanged;

        private List<DropdownValueItem> values = new List<DropdownValueItem>();

        private Dropdown dropdown;

        void Awake()
        {
            dropdown = GetComponent<Dropdown>();
            dropdown.onValueChanged.AddListener(OnChangeValue);
        }

        private void Start()
        {

        }

        public void AddOption(string id, string text)
        {
            Dropdown.OptionData option = new Dropdown.OptionData(text);
            dropdown.options.Add(option);
            DropdownValueItem item = new DropdownValueItem();
            item.id = id;
            item.text = text;
            values.Add(item);
            dropdown.RefreshShownValue();
        }

        public void ClearOptions()
        {
            values.Clear();
            dropdown.ClearOptions();
        }

        public void SetValue(string value)
        {
            int index = 0;
            foreach (DropdownValueItem item in values)
            {
                if (item.id == value)
                    dropdown.value = index;
                index++;
            }
        }

        public void SetValue(int index)
        {
            if (index >= 0 && index < dropdown.options.Count)
                dropdown.value = index;
        }

        private void OnChangeValue(int selected_index)
        {
            if (selected_index >= 0 && selected_index < values.Count)
            {
                DropdownValueItem value = values[selected_index];
                if (onValueChanged != null)
                    onValueChanged.Invoke(selected_index, value.id);
            }
        }

        public DropdownValueItem GetSelected()
        {
            if (dropdown.value >= 0 && dropdown.value < values.Count)
            {
                DropdownValueItem item = values[dropdown.value];
                return item;
            }
            return null;
        }

        public string GetSelectedValue()
        {
            DropdownValueItem item = GetSelected();
            if (item != null)
                return item.id;
            return "";
        }

        public string GetSelectedText()
        {
            DropdownValueItem item = GetSelected();
            if (item != null)
                return item.text;
            return "";
        }

        public int GetSelectedIndex()
        {
            return dropdown.value;
        }

        public int Count
        {
            get { return dropdown.options.Count; }
        }

        public bool interactable
        {
            get { return dropdown.interactable; }
            set { dropdown.interactable = value; }
        }

        public int value
        {
            get { return dropdown.value; }
            set { dropdown.value = value; dropdown.RefreshShownValue(); }
        }

        public List<DropdownValueItem> Items
        {
            get { return values; }
        }
    }
}