using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

namespace TcgEngine
{

    public class MouseInput
    {
        //Mouse input that supports both mouse and touchscreen with new input system

        public static bool IsLeftClick()
        {
            Pointer input = Pointer.current;
            if (input != null)
                return input.press.wasPressedThisFrame;
            return false;
        }

        public static bool IsMiddleClick()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.middleButton.wasPressedThisFrame;
            return false;
        }

        public static bool IsRightClick()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.rightButton.wasPressedThisFrame;
            return false;
        }

        public static bool IsLeftHold()
        {
            Pointer input = Pointer.current;
            if (input != null)
                return input.press.isPressed;
            return false;
        }

        public static bool IsMiddleHold()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.middleButton.isPressed;
            return false;
        }

        public static bool IsRightHold()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.rightButton.isPressed;
            return false;
        }

        public static bool IsLeftRelease()
        {
            Pointer input = Pointer.current;
            if (input != null)
                return input.press.wasReleasedThisFrame;
            return false;
        }

        public static bool IsMiddleRelease()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.middleButton.wasReleasedThisFrame;
            return false;
        }

        public static bool IsRightRelease()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.rightButton.wasReleasedThisFrame;
            return false;
        }

        public static Vector2 GetMousePosition()
        {
            Pointer input = Pointer.current;
            if (input != null)
                return input.position.ReadValue();
            return Vector2.zero;
        }

        public static Vector2 GetMouseDelta()
        {
            Pointer input = Pointer.current;
            if (input != null)
                return input.delta.ReadValue() * 0.1f; //Multiply by 0.1f to be more consistant with previous input system and gamepads
            return Vector2.zero;
        }

        public static float GetMouseScroll()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null)
                return mouse.scroll.ReadValue().y * 0.01f; //Multiply by 00.1f to be more consistant with previous input system and gamepads
            return 0f;
        }

    }
}