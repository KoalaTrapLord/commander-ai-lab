using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine.FX
{
    /// <summary>
    /// The crosshair target that appears when targeting with a spell
    /// </summary>

    public class AimTargetFX : MonoBehaviour
    {
        public GameObject fx;

        void Start()
        {

        }

        void Update()
        {
            bool visible = false;
            HandCard hcard = HandCard.GetDrag();
            if (hcard != null)
            {
                Card caster = hcard.GetCard();
                if (caster.CardData.IsRequireTarget())
                    visible = true;
            }

            if (fx.activeSelf != visible)
                fx.SetActive(visible);

            if (visible)
            {
                Vector3 dest = GameBoard.Get().RaycastMouseBoard();
                transform.position = dest;
            }
        }
    }
}
