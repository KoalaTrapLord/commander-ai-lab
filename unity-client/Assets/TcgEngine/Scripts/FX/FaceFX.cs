using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;

namespace TcgEngine.FX
{
    /// <summary>
    /// Rotate FX to face camera
    /// </summary>

    public class FaceFX : MonoBehaviour
    {
        public FaceType type;

        void Start()
        {
            Vector3 up = GameBoard.Get().transform.up;

            if (type == FaceType.FaceCamera)
            {
                GameCamera cam = GameCamera.Get();
                if (cam != null)
                {
                    Vector3 forward = cam.transform.forward;
                    transform.rotation = Quaternion.LookRotation(forward, up);
                }
            }

            if (type == FaceType.FaceCameraCenter)
            {
                GameCamera cam = GameCamera.Get();
                if (cam != null)
                {
                    Vector3 forward = transform.position - cam.transform.position;
                    transform.rotation = Quaternion.LookRotation(forward.normalized, up);
                }
            }

            if (type == FaceType.FaceBoard)
            {
                GameBoard board = GameBoard.Get();
                if (board != null)
                {
                    Vector3 forward = board.transform.forward;
                    transform.rotation = Quaternion.LookRotation(forward, up);
                }
            }
        }
    }

    public enum FaceType
    {
        FaceCamera = 0,         //Set same rotation as camera rotation
        FaceCameraCenter = 5,   //Face camera world position
        FaceBoard = 10          //Set same rotation as to board rotation
    }
}
