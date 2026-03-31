using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

namespace TcgEngine
{
    public class KeyInput
    {
        //Key if a key on the keyboard is pressed/held/released with new input system

        public static bool IsKeyPress(Key key)
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard != null)
            {
                return keyboard[key].wasPressedThisFrame;
            }
            return false;
        }

        public static bool IsKeyHold(Key key)
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard != null)
            {
                return keyboard[key].isPressed;
            }
            return false;
        }

        public static bool IsKeyRelease(Key key)
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard != null)
            {
                return keyboard[key].wasReleasedThisFrame;
            }
            return false;
        }
    }
}