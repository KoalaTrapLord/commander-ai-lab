using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Maps to GeneratedDeckCard from /api/deckgen/v3.</summary>
    [Serializable]
    public class GeneratedDeckCard
    {
        [JsonProperty("scryfall_id")] public string scryfallId;
        [JsonProperty("name")] public string name;
        [JsonProperty("type_line")] public string typeLine;
        [JsonProperty("mana_cost")] public string manaCost;
        [JsonProperty("cmc")] public float cmc;
        [JsonProperty("card_type")] public string cardType;
        [JsonProperty("roles")] public List<string> roles;
        [JsonProperty("source")] public string source;
        [JsonProperty("quantity")] public int quantity;
        [JsonProperty("image_url")] public string imageUrl;
        [JsonProperty("owned_qty")] public int ownedQty;
        [JsonProperty("is_proxy")] public bool isProxy;

        public override string ToString() => $"{name} ({manaCost})";
    }

    /// <summary>Response wrapper for /api/deckgen/v3.</summary>
    [Serializable]
    public class DeckGenResponse
    {
        [JsonProperty("cards")] public List<GeneratedDeckCard> cards;
        [JsonProperty("commander")] public string commander;
        [JsonProperty("strategy")] public string strategy;

        public override string ToString() => $"Generated deck: {commander} ({cards?.Count ?? 0} cards)";
    }
}
