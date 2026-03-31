using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine
{
    /// <summary>
    /// Change material based on Render Pipeline
    /// </summary>

    public class RPMat : MonoBehaviour
    {
        public Material mat_urp;

        private SpriteRenderer render;
        private Image image;
       
        void Start()
        {
            render = GetComponent<SpriteRenderer>();
            image = GetComponent<Image>();

            if (render != null && GameTool.IsURP())
                render.material = mat_urp;
            if (image != null && GameTool.IsURP())
                image.material = mat_urp;
        }

    }
}
