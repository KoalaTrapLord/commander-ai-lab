using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Paginated collection list from GET /api/collection.</summary>
    [Serializable]
    public class CollectionResponse
    {
        [JsonProperty("cards")] public List<CardModel> cards;
        [JsonProperty("total")] public int total;
        [JsonProperty("page")] public int page;
        [JsonProperty("per_page")] public int perPage;

        public override string ToString() => $"Collection: {total} cards (page {page})";
    }
}
