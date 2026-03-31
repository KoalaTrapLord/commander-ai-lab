using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Defines card variants
    /// </summary>

    [CreateAssetMenu(fileName = "VariantData", menuName = "TcgEngine/VariantData", order = 5)]
    public class VariantData : ScriptableObject
    {
        public string id;
        public string title;
        public Sprite frame;
        public Sprite frame_board;
        public Color color = Color.white;
        public int cost_factor = 1;
        public bool is_default;

        public static List<VariantData> variant_list = new List<VariantData>();

        public string GetSuffix()
        {
            return "_" + id;
        }

        public static void Load(string folder = "")
        {
            if (variant_list.Count == 0)
                variant_list.AddRange(Resources.LoadAll<VariantData>(folder));
        }

        public static VariantData GetDefault()
        {
            foreach (VariantData variant in GetAll())
            {
                if (variant.is_default)
                    return variant;
            }
            return null;
        }

        public static VariantData GetSpecial()
        {
            foreach (VariantData variant in GetAll())
            {
                if (!variant.is_default)
                    return variant;
            }
            return null;
        }

        public static VariantData Get(string id)
        {
            foreach (VariantData variant in GetAll())
            {
                if (variant.id == id)
                    return variant;
            }
            return GetDefault();
        }

        public static List<VariantData> GetAll()
        {
            return variant_list;
        }
    }
}