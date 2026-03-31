using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{

    public enum StatusType
    {
        None = 0,

        AddAttack = 4,      //Attack status can be used for attack boost limited for X turns 
        AddHP = 5,          //HP status can be used for hp boost limited for X turns 
        AddManaCost = 6,    //Mana Cost status can be used for mana cost increase/reduction limited for X turns 

        Stealth = 10,       //Cant be attacked until do action
        Invincibility = 12, //Cant be attacked for X turns
        Shell = 13,         //Receives no damage the first time
        Protection = 14,    //Taunt, gives Protected to other cards
        Protected = 15,     //Cards that are protected by taunt
        Armor = 16,         //Receives less damage
        SpellImmunity = 18, //Cant be targeted/damaged by spells

        Deathtouch = 20,    //Kills when attacking a character
        Fury = 22,          //Can attack twice per turn
        Intimidate = 23,    //Target doesnt counter when attacking
        Flying = 24,         //Can ignore taunt
        Trample = 26,         //Extra damage is assigned to player
        LifeSteal = 28,      //Heal player when fighting

        Silenced = 30,      //All abilities canceled
        Paralysed = 32,     //Cant do any actions for X turns
        Poisoned = 34,     //Lose hp each start of turn
        Sleep = 36,         //Doesnt untap at the start of turn


    }

    /// <summary>
    /// Defines all status effects data
    /// Status are effects that can be gained or lost with abilities, and that will affect gameplay
    /// Status can have a duration
    /// </summary>

    [CreateAssetMenu(fileName = "status", menuName = "TcgEngine/StatusData", order = 7)]
    public class StatusData : ScriptableObject
    {
        public StatusType effect;

        [Header("Display")]
        public string title;
        public Sprite icon;

        [TextArea(3, 5)]
        public string desc;

        [Header("FX")]
        public GameObject status_fx;

        [Header("AI")]
        public int hvalue;

        public static List<StatusData> status_list = new List<StatusData>();

        public string GetTitle()
        {
            return title;
        }

        public string GetDesc()
        {
            return GetDesc(1);
        }

        public string GetDesc(int value)
        {
            string des = desc.Replace("<value>", value.ToString());
            return des;
        }

        public static void Load(string folder = "")
        {
            if (status_list.Count == 0)
                status_list.AddRange(Resources.LoadAll<StatusData>(folder));
        }

        public static StatusData Get(StatusType effect)
        {
            foreach (StatusData status in GetAll())
            {
                if (status.effect == effect)
                    return status;
            }
            return null;
        }

        public static List<StatusData> GetAll()
        {
            return status_list;
        }
    }
}