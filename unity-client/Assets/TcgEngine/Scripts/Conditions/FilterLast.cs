using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    //Pick X first cards from the source array

    [CreateAssetMenu(fileName = "filter", menuName = "TcgEngine/Filter/Last", order = 10)]
    public class FilterLast : FilterData
    {
        public int amount = 1; //Number of first targets selected

        public override List<Card> FilterTargets(Game data, AbilityData ability, Card caster, List<Card> source, List<Card> dest)
        {
            int max = Mathf.Min(source.Count, amount);
            int min = source.Count - max;
            for (int i = source.Count-1; i >= min; i--)
                dest.Add(source[i]);
            return dest;
        }

        public override List<Player> FilterTargets(Game data, AbilityData ability, Card caster, List<Player> source, List<Player> dest)
        {
            int max = Mathf.Min(source.Count, amount);
            int min = source.Count - max;
            for (int i = source.Count - 1; i >= min; i--)
                dest.Add(source[i]);
            return dest;
        }

        public override List<Slot> FilterTargets(Game data, AbilityData ability, Card caster, List<Slot> source, List<Slot> dest)
        {
            int max = Mathf.Min(source.Count, amount);
            int min = source.Count - max;
            for (int i = source.Count - 1; i >= min; i--)
                dest.Add(source[i]);
            return dest;
        }
    }
}
