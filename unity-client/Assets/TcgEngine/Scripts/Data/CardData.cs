using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    public enum CardType
    {
        None = 0,
        Hero = 5,
        Character = 10,
        Spell = 20,
        Artifact = 30,
        Secret = 40,
        Equipment = 50,
    }

    public enum CardAvailability
    {
        Unlisted = 0,               //Card not displayed in the collection, use for summons
        Collectible = 10,           //Card can be unlocked in packs
        AlwaysAvailable = 20,       //Card can always be added to deck
    }

    /// <summary>
    /// Defines all card data
    /// </summary>

    [CreateAssetMenu(fileName = "card", menuName = "TcgEngine/CardData", order = 5)]
    public class CardData : ScriptableObject
    {
        public string id;

        [Header("Display")]
        public string title;
        public Sprite art_full;
        public Sprite art_board;

        [Header("Stats")]
        public CardType type;
        public TeamData team;
        public RarityData rarity;
        public int mana;
        public int attack;
        public int hp;

        [Header("Traits")]
        public TraitData[] traits;
        public TraitStat[] stats;

        [Header("Abilities")]
        public AbilityData[] abilities;

        [Header("Card Text")]
        [TextArea(3, 5)]
        public string text;

        [Header("Description")]
        [TextArea(5, 10)]
        public string desc;

        [Header("FX")]
        public GameObject spawn_fx;
        public GameObject death_fx;
        public GameObject attack_fx;
        public GameObject damage_fx;
        public GameObject idle_fx;
        public AudioClip spawn_audio;
        public AudioClip death_audio;
        public AudioClip attack_audio;
        public AudioClip damage_audio;

        [Header("Availability")]
        public CardAvailability availability;
        public int cost = 100;
        public PackData[] packs;

        public static List<CardData> card_list = new List<CardData>();                              //Faster access in loops
        public static Dictionary<string, CardData> card_dict = new Dictionary<string, CardData>();    //Faster access in Get(id)

        public static void Load(string folder = "")
        {
            if (card_list.Count == 0)
            {
                card_list.AddRange(Resources.LoadAll<CardData>(folder));

                foreach (CardData card in card_list)
                    card_dict.Add(card.id, card);
            }
        }

        public Sprite GetBoardArt(VariantData variant)
        {
            return art_board;
        }

        public Sprite GetFullArt(VariantData variant)
        {
            return art_full;
        }

        public string GetTitle()
        {
            return title;
        }

        public string GetText()
        {
            return text;
        }

        public string GetDesc()
        {
            return desc;
        }

        public string GetTypeId()
        {
            if (type == CardType.Hero)
                return "hero";
            if (type == CardType.Character)
                return "character";
            if (type == CardType.Artifact)
                return "artifact";
            if (type == CardType.Spell)
                return "spell";
            if (type == CardType.Secret)
                return "secret";
            if (type == CardType.Equipment)
                return "equipment";
            return "";
        }

        public string GetAbilitiesDesc()
        {
            string txt = "";
            foreach (AbilityData ability in abilities)
            {
                if (!string.IsNullOrWhiteSpace(ability.desc))
                    txt += "<b>" + ability.GetTitle() + ":</b> " + ability.GetDesc(this) + "\n";
            }
            return txt;
        }

        public bool IsCharacter()
        {
            return type == CardType.Character;
        }

        public bool IsSecret()
        {
            return type == CardType.Secret;
        }

        public bool IsBoardCard()
        {
            return type == CardType.Character || type == CardType.Artifact;
        }

        public bool IsRequireTarget()
        {
            return type == CardType.Equipment || IsRequireTargetSpell();
        }

        public bool IsRequireTargetSpell()
        {
            return type == CardType.Spell && HasAbility(AbilityTrigger.OnPlay, AbilityTarget.PlayTarget);
        }

        public bool IsEquipment()
        {
            return type == CardType.Equipment;
        }

        public bool IsDynamicManaCost()
        {
            return mana > 99;
        }

        public bool HasTrait(string trait)
        {
            foreach (TraitData t in traits)
            {
                if (t.id == trait)
                    return true;
            }
            return false;
        }

        public bool HasTrait(TraitData trait)
        {
            if(trait != null)
                return HasTrait(trait.id);
            return false;
        }

        public bool HasStat(string trait)
        {
            if (stats == null)
                return false;

            foreach (TraitStat stat in stats)
            {
                if (stat.trait.id == trait)
                    return true;
            }
            return false;
        }

        public bool HasStat(TraitData trait)
        {
            if(trait != null)
                return HasStat(trait.id);
            return false;
        }

        public int GetStat(string trait_id)
        {
            if (stats == null)
                return 0;

            foreach (TraitStat stat in stats)
            {
                if (stat.trait.id == trait_id)
                    return stat.value;
            }
            return 0;
        }

        public int GetStat(TraitData trait)
        {
            if(trait != null)
                return GetStat(trait.id);
            return 0;
        }

        public bool HasAbility(AbilityData tability)
        {
            foreach (AbilityData ability in abilities)
            {
                if (ability && ability.id == tability.id)
                    return true;
            }
            return false;
        }

        public bool HasAbility(AbilityTrigger trigger)
        {
            foreach (AbilityData ability in abilities)
            {
                if (ability && ability.trigger == trigger)
                    return true;
            }
            return false;
        }

        public bool HasAbility(AbilityTrigger trigger, AbilityTarget target)
        {
            foreach (AbilityData ability in abilities)
            {
                if (ability && ability.trigger == trigger && ability.target == target)
                    return true;
            }
            return false;
        }

        public AbilityData GetAbility(AbilityTrigger trigger)
        {
            foreach (AbilityData ability in abilities)
            {
                if (ability && ability.trigger == trigger)
                    return ability;
            }
            return null;
        }

        public bool HasPack(PackData pack)
        {
            foreach (PackData apack in packs)
            {
                if (apack == pack)
                    return true;
            }
            return false;
        }

        public bool IsDeckbuilding()
        {
            return availability == CardAvailability.Collectible || availability == CardAvailability.AlwaysAvailable;
        }

        public bool IsCollectible()
        {
            return availability == CardAvailability.Collectible;
        }

        public static CardData Get(string id)
        {
            if (id == null)
                return null;
            bool success = card_dict.TryGetValue(id, out CardData card);
            if (success)
                return card;
            return null;
        }

        public static List<CardData> GetAllDeckbuilding()
        {
            List<CardData> multi_list = new List<CardData>();
            foreach (CardData acard in GetAll())
            {
                if (acard.IsDeckbuilding())
                    multi_list.Add(acard);
            }
            return multi_list;
        }

        public static List<CardData> GetAll(PackData pack)
        {
            List<CardData> multi_list = new List<CardData>();
            foreach (CardData acard in GetAll())
            {
                if (acard.HasPack(pack))
                    multi_list.Add(acard);
            }
            return multi_list;
        }

        public static List<CardData> GetAll()
        {
            return card_list;
        }
    }
}