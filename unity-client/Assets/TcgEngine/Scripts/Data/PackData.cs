using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Defines all packs data
    /// </summary>

    [CreateAssetMenu(fileName = "PackData", menuName = "TcgEngine/PackData", order = 5)]
    public class PackData : ScriptableObject
    {
        public string id;

        [Header("Content")]
        public PackType type;
        public int cards = 5;   //Cards per pack
        public PackRarity[] rarities_1st;  //Probability of each rarity, for first card
        public PackRarity[] rarities;      //Probability of each rarity, for other cards
        public PackVariant[] variants;      //Probability of each variant, for other cards

        [Header("Display")]
        public string title;
        public Sprite pack_img;
        public Sprite cardback_img;
        [TextArea(5, 10)]
        public string desc;
        public int sort_order;

        [Header("Availability")]
        public bool available = true;
        public int cost = 100;  //Cost to buy

        public static List<PackData> pack_list = new List<PackData>();

        public static void Load(string folder = "")
        {
            if (pack_list.Count == 0)
                pack_list.AddRange(Resources.LoadAll<PackData>(folder));

            pack_list.Sort((PackData a, PackData b) => {
                if (a.sort_order == b.sort_order)
                    return a.id.CompareTo(b.id);
                else
                    return a.sort_order.CompareTo(b.sort_order);
            });
        }

        public string GetTitle()
        {
            return title;
        }

        public string GetDesc()
        {
            return desc;
        }

        public static PackData Get(string id)
        {
            foreach (PackData pack in GetAll())
            {
                if (pack.id == id)
                    return pack;
            }
            return null;
        }

        public static List<PackData> GetAllAvailable()
        {
            List<PackData> valid_list = new List<PackData>();
            foreach (PackData apack in GetAll())
            {
                if (apack.available)
                    valid_list.Add(apack);
            }
            return valid_list;
        }

        public static List<PackData> GetAll()
        {
            return pack_list;
        }
    }

    public enum PackType
    {
        Random = 0,
        Fixed = 10,
    }

    [System.Serializable]
    public struct PackRarity
    {
        public RarityData rarity;
        public int probability;
    }

    [System.Serializable]
    public struct PackVariant
    {
        public VariantData variant;
        public int probability;
    }
}