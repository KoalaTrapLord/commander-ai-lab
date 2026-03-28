using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Tracks poison counters for a seat (0-10).
    /// Activates pip toggles and triggers elimination at 10.
    /// </summary>
    public class PoisonCounter : MonoBehaviour
    {
        [SerializeField] private int       seatIndex;
        [SerializeField] private Toggle[]  pips;          // 10 Toggle GameObjects
        [SerializeField] private TMP_Text  countLabel;
        [SerializeField] private Button    addPoisonBtn;
        [SerializeField] private Button    removePoisonBtn;

        private int _count = 0;

        private void Start()
        {
            addPoisonBtn?.onClick.AddListener(()    => AddPoison(1));
            removePoisonBtn?.onClick.AddListener(() => AddPoison(-1));
            Refresh();
        }

        public void AddPoison(int delta)
        {
            _count = Mathf.Clamp(_count + delta, 0, 10);
            Refresh();
            if (_count >= 10)
                GameStateManager.Instance?.EliminatePlayer(seatIndex, "poison");
        }

        public void SetPoison(int value)
        {
            _count = Mathf.Clamp(value, 0, 10);
            Refresh();
        }

        private void Refresh()
        {
            if (countLabel) countLabel.text = _count.ToString();
            for (int i = 0; i < pips.Length; i++)
                if (pips[i] != null) pips[i].isOn = i < _count;
        }
    }
}
