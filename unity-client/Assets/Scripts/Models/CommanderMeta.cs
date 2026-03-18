using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Commander archetype info from /api/lab/meta/commanders.</summary>
    [Serializable]
    public class CommanderMeta
    {
        [JsonProperty("name")] public string name;
        [JsonProperty("source")] public string source;
        [JsonProperty("archetype")] public string archetype;
        [JsonProperty("colorIdentity")] public List<string> colorIdentity;

        public override string ToString() => $"{name} ({archetype}) [{string.Join(",", colorIdentity ?? new List<string>())}]";
    }
}
