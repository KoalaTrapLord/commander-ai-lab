using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.FX
{
    /// <summary>
    /// Dice roll FX, coded for 6 faces only
    /// </summary>

    public class DiceRollFX : MonoBehaviour
    {
        public int value;

        [Header("Anim")]
        public Transform dice;
        public float roll_speed = 20f;
        public float roll_duration = 1f;
        public AudioClip start_audio;
        public AudioClip end_audio;

        private Vector3[] dir;

        private bool ended = false;
        private float timer = 0f;
        private float x = 0f;
        private float y = 0f;
        private float z = 0f;

        void Start()
        {
            //Direction of each face
            dir = new Vector3[6];
            dir[0] = Vector3.forward;  //one
            dir[1] = Vector3.up;  //two
            dir[2] = Vector3.right;  //three
            dir[3] = Vector3.left;  //four
            dir[4] = Vector3.down;  //five
            dir[5] = Vector3.back;  //six

            AudioTool.Get().PlaySFX("dice", start_audio);
        }

        void Update()
        {
            timer += Time.deltaTime;

            if (!ended)
            {
                if (timer < roll_duration)
                {
                    x += 5f * Time.deltaTime;
                    y += 7f * Time.deltaTime;
                    dice.Rotate(x * roll_speed, y * roll_speed, z * roll_speed, Space.Self);
                }
                else
                {
                    ended = true;
                    timer = 0f;
                    AudioTool.Get().PlaySFX("dice", end_audio);
                }
            }

            if (ended)
            {
                if (value >= 1 && value <= dir.Length)
                {
                    Vector3 target = dir[value - 1];
                    Vector3 up = target.y > target.z ? Vector3.back : Vector3.up;
                    Quaternion trot = Quaternion.LookRotation(target, up);
                    dice.localRotation = Quaternion.Slerp(dice.localRotation, trot, roll_speed * Time.deltaTime);
                }

                if (timer > 1f)
                {
                    Destroy(gameObject);
                }
            }
        }
    }
}
