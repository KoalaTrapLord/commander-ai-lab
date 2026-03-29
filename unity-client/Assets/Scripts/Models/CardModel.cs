using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>
    /// Represents a single MTG card from the collection or deck.
    /// Maps to the card objects returned by /api/collection and /api/decks.
    /// </summary>
    [Serializable]
    public class CardModel
    {
        [JsonProperty("id")] public string id;
        [JsonProperty("name")] public string name;
        [JsonProperty("oracle_id")] public string oracleId;
        [JsonProperty("scryfall_id")] public string scryfallId;
        [JsonProperty("image_uri")] public string imageUri;
        [JsonProperty("mana_cost")] public string manaCost;
        [JsonProperty("cmc")] public float cmc;
        [JsonProperty("type_line")] public string typeLine;
        [JsonProperty("card_type")] public string cardType;
        [JsonProperty("colors")] public List<string> colors;
        [JsonProperty("color_identity")] public List<string> colorIdentity;
        [JsonProperty("set")] public string set;
        [JsonProperty("rarity")] public string rarity;
        [JsonProperty("oracle_text")] public string oracleText;
        [JsonProperty("power")] public string power;
        [JsonProperty("toughness")] public string toughness;
        [JsonProperty("quantity")] public int quantity;
        [JsonProperty("owned_qty")] public int ownedQty;
        [JsonProperty("is_proxy")] public bool isProxy;
        [JsonProperty("roles")] public List<string> roles;
        [JsonProperty("source")] public string source;

        // ── Battleground runtime state (not serialized to JSON) ───────────────
        [NonSerialized] public bool isTapped;
        [NonSerialized] public bool isSummoningSick;
        [NonSerialized] public int ownerSeat = -1;
        [NonSerialized] public BattleZone currentZone = BattleZone.Library;
        [NonSerialized] public Dictionary<string, int> counters = new();

        public override string ToString() => $"{name} ({manaCost}) [{typeLine}]";
    }

    public enum BattleZone
    {
        Library,
        Hand,
        Battlefield,
        Graveyard,
        Exile,
        CommandZone,
        Stack
    }
}
