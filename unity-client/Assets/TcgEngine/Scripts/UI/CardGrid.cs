using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Grid of cards in the collection panel
    /// </summary>

    public class CardGrid : MonoBehaviour
    {
        private GridLayoutGroup grid;
        private RectTransform rect;

        void Awake()
        {
            grid = GetComponent<GridLayoutGroup>();
            rect = GetComponent<RectTransform>();
        }

        public void GetColumnAndRow(out int rows, out int columns)
        {
            rows = 0;
            columns = 0;

            if (grid.transform.childCount == 0)
                return;

            //Get the first child GameObject of the GridLayoutGroup
            RectTransform firstChildObj = grid.transform.GetChild(0).GetComponent<RectTransform>();
            Vector2 firstChildPos = firstChildObj.anchoredPosition;
            bool stopCountingCol = false;

            if (firstChildPos.x == 0 && firstChildPos.y == 0)
                return;

            //Column and row are now 1
            rows = 1;
            columns = 1;

            //Loop through the rest of the child object
            for (int i = 1; i < grid.transform.childCount; i++)
            {
                //Get the next child
                RectTransform currentChildObj = grid.transform.GetChild(i).GetComponent<RectTransform>();
                Vector2 currentChildPos = currentChildObj.anchoredPosition;

                //check if column or row
                if (Mathf.Abs(firstChildPos.x - currentChildPos.x) < 0.1f)
                {
                    rows++;
                    stopCountingCol = true;
                }
                else
                {
                    if (!stopCountingCol)
                        columns++;
                }
            }
        }

        public GridLayoutGroup GetGrid()
        {
            return grid;
        }

        public RectTransform GetRect()
        {
            return rect;
        }
    }
}