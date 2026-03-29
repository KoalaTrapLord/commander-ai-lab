using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using CommanderAILab.UI;

namespace CommanderAILab.Models
{
    /// <summary>Full live game state snapshot pushed by the server on state_update events.</summary>
    [Serializable]
    public class GameState
    {
        [JsonProperty("seats")]       public List<SeatState> seats;
        [JsonProperty("active_seat")] public int activeSeat;
        [JsonProperty("turn_number")] public int turnNumber;
        [JsonProperty("phase")]       public string phase;
        [JsonProperty("stack")]       public List<StackZoneController.StackItem> stack;
    }

    /// <summary>Per-seat state within a GameState snapshot.</summary>
    [Serializable]
    public class SeatState
    {
        [JsonProperty("seat_index")]           public int seatIndex;
        [JsonProperty("player_name")]          public string playerName;
        [JsonProperty("life")]                 public int life;
        [JsonProperty("hand")]                 public List<CardModel> hand;
        [JsonProperty("battlefield")]          public List<CardModel> battlefield;
        [JsonProperty("graveyard")]            public List<CardModel> graveyard;
        [JsonProperty("exile")]                public List<CardModel> exile;
        [JsonProperty("commander")]            public CardModel commander;
        [JsonProperty("commander_cast_count")] public int commanderCastCount;
        /// <summary>Cumulative commander damage received from each seat index (length 4).</summary>
        [JsonProperty("commander_damage_from")] public int[] commanderDamageFrom;
        [JsonProperty("poison_counters")]      public int poisonCounters;
        [JsonProperty("mana_pool")]            public Dictionary<string, int> manaPool;
        [JsonProperty("is_eliminated")]        public bool isEliminated;
    }
}
