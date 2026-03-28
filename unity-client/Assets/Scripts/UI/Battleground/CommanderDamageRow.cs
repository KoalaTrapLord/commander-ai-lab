using UnityEngine;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Displays cumulative commander damage received from each opposing seat.
    /// Triggers elimination when any source reaches 21.
    /// Attach one to each seat panel; set SeatIndex in inspector.
    /// </summary>
    public class CommanderDamageRow : MonoBehaviour
    {
        /// <summary>The seat this row belongs to (receives damage).</summary>
        [SerializeField] private int seatIndex;

        /// <summary>
        /// Labels for damage received from each seat.
        /// fromSeatLabels[i] corresponds to global seat i.
        /// The label for this seat's own index will be hidden (can't deal commander damage to yourself).
        /// </summary>
        [SerializeField] private TMP_Text[] fromSeatLabels; // length 4

        private readonly int[] _damage = new int[4];

        private void Start()
        {
            // Hide this seat's own label
            if (fromSeatLabels != null && seatIndex < fromSeatLabels.Length
                && fromSeatLabels[seatIndex] != null)
                fromSeatLabels[seatIndex].gameObject.SetActive(false);

            RefreshAllLabels();
        }

        public void AddDamage(int fromSeat, int amount)
        {
            if (fromSeat < 0 || fromSeat >= 4 || fromSeat == seatIndex) return;
            _damage[fromSeat] = Mathf.Max(0, _damage[fromSeat] + amount);
            RefreshLabel(fromSeat);

            if (_damage[fromSeat] >= 21)
                GameStateManager.Instance?.EliminatePlayer(seatIndex, "commander_damage");
        }

        public void SetDamage(int fromSeat, int value)
        {
            if (fromSeat < 0 || fromSeat >= 4 || fromSeat == seatIndex) return;
            _damage[fromSeat] = Mathf.Max(0, value);
            RefreshLabel(fromSeat);
        }

        public int GetDamage(int fromSeat) =>
            (fromSeat >= 0 && fromSeat < 4) ? _damage[fromSeat] : 0;

        private void RefreshLabel(int fromSeat)
        {
            if (fromSeatLabels == null || fromSeat >= fromSeatLabels.Length) return;
            var lbl = fromSeatLabels[fromSeat];
            if (lbl == null) return;
            lbl.text = _damage[fromSeat] > 0 ? _damage[fromSeat].ToString() : "0";
            lbl.color = _damage[fromSeat] >= 21 ? Color.red : Color.white;
        }

        private void RefreshAllLabels()
        {
            for (int i = 0; i < 4; i++) RefreshLabel(i);
        }
    }
}
