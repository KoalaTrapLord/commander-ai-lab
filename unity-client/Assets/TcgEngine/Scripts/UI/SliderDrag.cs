using UnityEngine;
using System.Collections;
using UnityEngine.EventSystems;
using UnityEngine.Events;
using UnityEngine.UI;

namespace TcgEngine.UI
{

    public class SliderDrag : MonoBehaviour, IPointerUpHandler, IPointerDownHandler
    {
        public UnityAction onStartDrag;
        public UnityAction onEndDrag;
        public UnityAction onValueChanged;

        private Slider slider;

        void Awake()
        {
            slider = GetComponent<Slider>();
            slider.onValueChanged.AddListener((float v) => { onValueChanged?.Invoke(); });
        }

        public void OnPointerDown(PointerEventData eventData)
        {
            onStartDrag?.Invoke();
        }

        public void OnPointerUp(PointerEventData eventData)
        {
            onEndDrag?.Invoke();
        }

        public Slider Slider
        {
            get
            {
                if (slider == null)
                    slider = GetComponent<Slider>();
                return slider;
            }
        }

        public float maxValue
        {
            get { return Slider.maxValue; }
            set { Slider.maxValue = value; }
        }

        public float minValue
        {
            get { return Slider.minValue; }
            set { Slider.minValue = value; }
        }

        public float value
        {
            get { return Slider.value; }
            set { Slider.value = value; }
        }
    }
}