using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    [Serializable]
    public class DeckModel
    {
        [JsonProperty("id")] public string id;
        [JsonProperty("name")] public string name;
        [JsonProperty("commander")] public string commander;
        [JsonProperty("colors")] public List<string> colors;
        [JsonProperty("cards")] public List<CardModel> cards;
        [JsonProperty("card_count")] public int cardCount;
        [JsonProperty("created_at")] public string createdAt;
        [JsonProperty("updated_at")] public string updatedAt;

        public override string ToString() => $"{name} ({commander}) [{cardCount} cards]";
    }
}
