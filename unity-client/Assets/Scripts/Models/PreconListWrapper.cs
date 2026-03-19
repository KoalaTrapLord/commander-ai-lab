using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Wrapper for the precon list returned by /api/lab/precons.</summary>
    [Serializable]
    public class PreconListWrapper
    {
        [JsonProperty("precons")] public List<string> precons;
    }
}
