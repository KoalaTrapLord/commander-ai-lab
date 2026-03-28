using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// A single seat pill inside TurnOrderBar.
    /// Shows player name, current life, and highlights when it is that seat's turn.
    /// </summary>
    public class TurnOrderPill : MonoBehaviour
    {
        [SerializeField] private TMP_Text   playerNameLabel;
        [SerializeField] private TMP_Text   lifeLabel;
        [SerializeField] private Image      pillBackground;
        [SerializeField] private GameObject youBadge;          // "YOU" label, only visible on seat 0

        [Header("Colors")]
        [SerializeField] private Color activeColor   = new Color(1f, 0.85f, 0f);
        [SerializeField] private Color inactiveColor = new Color(0.25f, 0.25f, 0.25f);
        [SerializeField] private Color eliminatedColor = new Color(0.4f, 0.4f, 0.4f, 0.5f);

        private bool _isEliminated;

        public void SetPlayerName(string playerName)
        {
            if (playerNameLabel) playerNameLabel.text = playerName;
        }

        public void UpdateLife(int life)
        {
            if (lifeLabel) lifeLabel.text = life.ToString();
        }

        public void ShowYouBadge(bool show)
        {
            if (youBadge) youBadge.SetActive(show);
        }

        public void SetActive(bool active)
        {
            if (_isEliminated) return;
            if (pillBackground) pillBackground.color = active ? activeColor : inactiveColor;
        }

        public void SetEliminated()
        {
            _isEliminated = true;
            if (pillBackground) pillBackground.color = eliminatedColor;
            if (playerNameLabel)
            {
                playerNameLabel.fontStyle = TMPro.FontStyles.Strikethrough;
                playerNameLabel.color     = Color.gray;
            }
        }
    }
}
