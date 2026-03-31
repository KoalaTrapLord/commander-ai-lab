using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.Client
{
    /// <summary>
    /// Base class for BoardSlot, BoardSlotPlayer and BoardSlotGroup
    /// </summary>

    public class BSlot : MonoBehaviour
    {
        protected SpriteRenderer render;
        protected Collider collide;
        protected Bounds bounds;
        protected float start_alpha = 0f;
        protected float current_alpha = 0f;
        protected float target_alpha = 0f;

        private static List<BSlot> slot_list = new List<BSlot>();

        protected virtual void Awake()
        {
            slot_list.Add(this);
            render = GetComponent<SpriteRenderer>();
            collide = GetComponent<Collider>();
            start_alpha = render.color.a;
            render.color = new Color(render.color.r, render.color.g, render.color.b, 0f);
            bounds = collide.bounds;
        }

        protected virtual void OnDestroy()
        {
            slot_list.Remove(this);
        }

        protected virtual void Update()
        {
            current_alpha = Mathf.MoveTowards(current_alpha, target_alpha * start_alpha, 2f * Time.deltaTime);
            render.color = new Color(render.color.r, render.color.g, render.color.b, current_alpha);
        }

        public virtual Slot GetSlot()
        {
            return Slot.None;
        }

        public virtual Slot GetSlot(Vector3 wpos)
        {
            return GetSlot();
        }

        public virtual Slot GetEmptySlot(Vector3 wpos)
        {
            return GetSlot();
        }
        
        public virtual Card GetSlotCard(Vector3 wpos)
        {
            Game gdata = GameClient.Get().GetGameData();
            Slot slot = GetSlot(wpos);
            return gdata.GetSlotCard(slot);
        }

        public virtual Vector3 GetPosition(Slot slot)
        {
            return transform.position;
        }

        public virtual Player GetPlayer()
        {
            return null;
        }

        public virtual bool HasSlot(Slot slot)
        {
            Slot aslot = GetSlot();
            return aslot == slot;
        }

        public virtual bool IsPlayer()
        {
            Slot slot = GetSlot();
            return slot.x == 0 && slot.y == 0;
        }

        public virtual bool IsInside(Vector3 wpos)
        {
            return bounds.Contains(wpos);
        }

        public static BSlot GetNearest(Vector3 pos)
        {
            BSlot nearest = null;
            float min_dist = 999f;
            foreach (BSlot slot in GetAll())
            {
                float dist = (slot.transform.position - pos).magnitude;
                if (slot.IsInside(pos) && dist < min_dist)
                {
                    min_dist = dist;
                    nearest = slot;
                }
            }
            return nearest;
        }

        public static BSlot Get(Slot slot)
        {
            foreach (BSlot bslot in GetAll())
            {
                if (bslot.HasSlot(slot))
                    return bslot;
            }
            return null;
        }

        public static List<BSlot> GetAll()
        {
            return slot_list;
        }
    }

    public enum BoardSlotType
    {
        Fixed = 0,              //x,y,p = slot
        PlayerSelf = 5,         //p = client player id
        PlayerOpponent = 7,     //p = client's opponent player id
        FlipX = 10,              //p=0,   x=unchanged for first player,  x=reversed for second player
        FlipY = 11,              //p=0,   y=unchanged for first player,  y=reversed for second player
    }
}
