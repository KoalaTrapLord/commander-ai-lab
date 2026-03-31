using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// Add to any UI component to make it visible or invisible based on the device
    /// </summary>
    
    public class DeviceVisibility : MonoBehaviour
    {
        public bool desktop = true;
        public bool mobile = true;

        void Start()
        {
            bool ismobile = GameTool.IsMobile();
            if (ismobile && !mobile)
                gameObject.SetActive(false);
            else if (!ismobile && !desktop)
                gameObject.SetActive(false);
        }
    }
}