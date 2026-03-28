using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Runtime data model for a token on the battlefield.</summary>
    [Serializable]
    public class TokenModel
    {
        public string id;
        public string name;
        public string power;
        public string toughness;
        /// <summary>Single letter: W U B R G C</summary>
        public string colorCode = "C";
        public int ownerSeat;
        public int qty = 1;
        public bool isTapped;
        public Dictionary<string, int> counters = new();

        public string PTString =>
            (!string.IsNullOrEmpty(power) && !string.IsNullOrEmpty(toughness))
                ? $"{power}/{toughness}" : "";
    }
}
