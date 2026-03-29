using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// A single phase pill in the PhaseTrackerWidget strip.
    /// Changes color, font weight, and scale when activated.
    /// </summary>
    public class PhaseStepButton : MonoBehaviour
    {
        [SerializeField] private Image      background;
        [SerializeField] private TMP_Text   label;

        [Header("Colors")]
        [SerializeField] private Color activeColor   = new Color(1f, 0.85f, 0f);     // amber/yellow
        [SerializeField] private Color inactiveColor = new Color(0.2f, 0.2f, 0.2f);  // dark grey

        private Vector3 _baseScale;

        private void Awake() => _baseScale = transform.localScale;

        public void SetActive(bool active)
        {
            if (background) background.color = active ? activeColor : inactiveColor;
            if (label)      label.fontStyle   = active ? TMPro.FontStyles.Bold : TMPro.FontStyles.Normal;
            transform.localScale = active ? _baseScale * 1.1f : _baseScale;
        }
    }
}
