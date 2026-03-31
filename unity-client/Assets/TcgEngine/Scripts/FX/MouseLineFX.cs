using TcgEngine.Client;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine;

namespace TcgEngine.FX
{
    /// <summary>
    /// Line FX that appear when dragin a board card to attack
    /// </summary>

    public class MouseLineFX : MonoBehaviour
    {
        public GameObject dot_template;
        public float dot_spacing = 0.2f;

        private List<GameObject> dot_list = new List<GameObject>();
        private List<Vector3> points = new List<Vector3>();

        void Start()
        {
            dot_template.SetActive(false);
        }

        void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            RefreshLine();
            RefreshRender();
        }

        private void RefreshLine()
        {
            points.Clear();

            Game gdata = GameClient.Get().GetGameData();
            PlayerControls controls = PlayerControls.Get();
            BoardCard bcard = controls.GetSelected();

            bool visible = false;
            Vector3 source = Vector3.zero;
            if (bcard != null)
            {
                source = bcard.transform.position;
                visible = true;
            }

            HandCard drag = HandCard.GetDrag();
            if (drag != null)
            {
                source = drag.transform.position;
                visible = drag.GetCardData().IsRequireTarget();
            }

            if (gdata.selector == SelectorType.SelectTarget && gdata.selector_player_id == GameClient.Get().GetPlayerID())
            {
                BoardCard caster = BoardCard.Get(gdata.selector_caster_uid);
                if (caster != null)
                {
                    source = caster.transform.position;
                    visible = true;
                }
            }

            if (visible)
            {
                Vector3 dest = GameBoard.Get().RaycastMouseBoard();
                Vector3 dir = (dest - source).normalized;
                float dist = (dest - source).magnitude;

                float value = 0f;
                while (value < dist)
                {
                    Vector3 pos = source + dir * value;
                    points.Add(pos);

                    value += dot_spacing;
                }
            }
        }

        private void RefreshRender()
        {
            while (dot_list.Count < points.Count)
            {
                AddDot();
            }

            int index = 0;
            foreach (GameObject dot in dot_list)
            {
                bool active = false;
                if (index < points.Count)
                {
                    Vector3 pos = points[index];
                    dot.transform.position = pos;
                    active = true;
                }

                if (dot.activeSelf != active)
                    dot.SetActive(active);

                index++;
            }
        }

        public void AddDot()
        {
            GameObject dot = Instantiate(dot_template, transform);
            dot.SetActive(true);
            dot_list.Add(dot);
        }
    }
}
