using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Unity.Netcode;

namespace TcgEngine
{
    /// <summary>
    /// Represent a slot in gameplay (data only)
    /// </summary>

    [System.Serializable]
    public struct Slot : INetworkSerializable
    {
        public int x; //From 1 to 5
        public int y; //Not in use, could be used to add more rows or different locations on the board
        public int p; //0 or 1, represent player ID

        public static int x_min = 1; //Dont change this, should start at 1  (0,0,0 represent invalid slot)
        public static int x_max = 5; //Number of slots in a row/zone

        public static int y_min = 1; //Dont change this, should start at 1  (0,0,0 represent invalid slot)
        public static int y_max = 1; //Set this to the number of rows/locations you want to have

        public static bool ignore_p = false; //Set to true if you dont want to use P value

        private static Dictionary<int, List<Slot>> player_slots = new Dictionary<int, List<Slot>>();
        private static List<Slot> all_slots = new List<Slot>();

        public Slot(int pid)
        {
            this.x = 0;
            this.y = 0;
            this.p = pid;
        }

        public Slot(int x, int y, int pid)
        {
            this.x = x;
            this.y = y;
            this.p = pid;
        }

        public Slot(SlotXY slot, int pid)
        {
            this.x = slot.x;
            this.y = slot.y;
            this.p = pid;
        }

        public bool IsInRangeX(Slot slot, int range)
        {
            return Mathf.Abs(x - slot.x) <= range;
        }

        public bool IsInRangeY(Slot slot, int range)
        {
            return Mathf.Abs(y - slot.y) <= range;
        }

        public bool IsInRangeP(Slot slot, int range)
        {
            return Mathf.Abs(p - slot.p) <= range;
        }

        //No Diagonal, Diagonal = 2 dist
        public bool IsInDistanceStraight(Slot slot, int dist)
        {
            int r = Mathf.Abs(x - slot.x) + Mathf.Abs(y - slot.y) + Mathf.Abs(p - slot.p);
            return r <= dist;
        }

        //Diagonal = 1 dist
        public bool IsInDistance(Slot slot, int dist)
        {
            int dx = Mathf.Abs(x - slot.x);
            int dy = Mathf.Abs(y - slot.y);
            int dp = Mathf.Abs(p - slot.p);
            return dx <= dist && dy <= dist && dp <= dist;
        }

        public bool IsPlayerSlot()
        {
            return x == 0 && y == 0;
        }

        //Check if the slot is valid one (or if out of board)
        public bool IsValid()
        {
            return x >= x_min && x <= x_max && y >= y_min && y <= y_max && p >= 0;
        }

        public static int MaxP
        {
            get { return ignore_p ? 0 : 1; } 
        }

        //Return slot P-value of player, usually its same as player_id, unless we ignore P value then its 0 for all
        public static int GetP(int pid)
        {
            return ignore_p ? 0 : pid;
        }

        //Get a random slot on player side
        public static Slot GetRandom(int pid, System.Random rand)
        {
            int p = GetP(pid);
            if (y_max > y_min)
                return new Slot(rand.Next(x_min, x_max + 1), rand.Next(y_min, y_max + 1), p);
            return new Slot(rand.Next(x_min, x_max + 1), y_min, p);
        }

        //Get a random slot amongts all valid ones
        public static Slot GetRandom(System.Random rand)
        {
            if (y_max > y_min)
                return new Slot(rand.Next(x_min, x_max + 1), rand.Next(y_min, y_max + 1), rand.Next(0, 2));
            return new Slot(rand.Next(x_min, x_max + 1), y_min, rand.Next(0, 2));
        }
		
		public static Slot Get(int x, int y, int p)
        {
            List<Slot> slots = GetAll();
            foreach (Slot slot in slots)
            {
                if (slot.x == x && slot.y == y && slot.p == p)
                    return slot;
            }
            return new Slot(x, y, p);
        }

        //Get all slots on player side
        public static List<Slot> GetAll(int pid)
        {
            int p = GetP(pid);

            if (player_slots.ContainsKey(p))
                return player_slots[p]; //Faster access

            List<Slot> list = new List<Slot>();
            for (int y = y_min; y <= y_max; y++)
            {
                for (int x = x_min; x <= x_max; x++)
                {
                    list.Add(new Slot(x, y, p));
                }
            }
            player_slots[p] = list;
            return list;
        }

        //Get all valid slots
        public static List<Slot> GetAll()
        {
            if (all_slots.Count > 0)
                return all_slots; //Faster access

            for (int p = 0; p <= MaxP; p++)
            {
                for (int y = y_min; y <= y_max; y++)
                {
                    for (int x = x_min; x <= x_max; x++)
                    {
                        all_slots.Add(new Slot(x, y, p));
                    }
                }
            }
            return all_slots;
        }

        public static bool operator ==(Slot slot1, Slot slot2)
        {
            return slot1.x == slot2.x && slot1.y == slot2.y && slot1.p == slot2.p;
        }

        public static bool operator !=(Slot slot1, Slot slot2)
        {
            return slot1.x != slot2.x || slot1.y != slot2.y || slot1.p != slot2.p;
        }

        public override bool Equals(object o)
        {
            return base.Equals(o);
        }

        public override int GetHashCode()
        {
            return base.GetHashCode();
        }

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref x);
            serializer.SerializeValue(ref y);
            serializer.SerializeValue(ref p);
        }

        public static Slot None
        {
            get { return new Slot(0, 0, 0); }
        }
    }

    [System.Serializable]
    public struct SlotXY
    {
        public int x;
        public int y;
    }
}
