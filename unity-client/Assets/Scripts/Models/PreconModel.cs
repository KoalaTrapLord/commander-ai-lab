using System;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Maps to DeckInfo from /api/lab/precons.</summary>
    [Serializable]
    public class PreconModel
    {
        [JsonProperty("name")] public string name;
        [JsonProperty("filename")] public string filename;

        public override string ToString() => $"{name} ({filename})";
    }
}
