using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Visual row for a single item on the stack.
    /// Shows card/ability name, caster seat color, stack position, and targets.
    /// </summary>
    public class StackItemView : MonoBehaviour
    {
        [SerializeField] private TMP_Text   cardNameLabel;
        [SerializeField] private TMP_Text   casterLabel;
        [SerializeField] private TMP_Text   targetsLabel;
        [SerializeField] private TMP_Text   stackPositionLabel;
        [SerializeField] private Image      seatColorStrip;

        private static readonly Color[] SeatColors =
        {
            new Color(0.2f, 0.6f, 1f),   // seat 0 — blue (human)
            new Color(1f,  0.4f, 0.4f),  // seat 1 — red
            new Color(0.4f, 1f, 0.4f),   // seat 2 — green
            new Color(1f,  0.85f, 0.2f)  // seat 3 — gold
        };

        public void Bind(StackZoneController.StackItem item, int displayPosition)
        {
            if (cardNameLabel)
                cardNameLabel.text = item.isAbility ? $"⚡ {item.cardName}" : item.cardName;

            if (casterLabel)
                casterLabel.text = item.casterSeat == 0 ? "You" : $"Seat {item.casterSeat}";

            if (seatColorStrip)
            {
                int seat = Mathf.Clamp(item.casterSeat, 0, SeatColors.Length - 1);
                seatColorStrip.color = SeatColors[seat];
            }

            if (stackPositionLabel)
                stackPositionLabel.text = displayPosition == 0 ? "[TOP]" : $"[{displayPosition}]";

            if (targetsLabel)
            {
                if (item.targets != null && item.targets.Count > 0)
                    targetsLabel.text = "\u2192 " + string.Join(", ", item.targets);
                else
                    targetsLabel.text = "";
            }
        }
    }
}
