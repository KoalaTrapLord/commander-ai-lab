using System;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Maps to POST /api/coach/chat response.</summary>
    [Serializable]
    public class CoachResponse
    {
        [JsonProperty("reply")] public string reply;
        [JsonProperty("deck_report")] public string deckReport;
        [JsonProperty("suggestions")] public string[] suggestions;

        public override string ToString() => reply ?? "(empty coach response)";
    }
}
