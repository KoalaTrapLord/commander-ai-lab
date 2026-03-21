using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>
    /// Full game state snapshot from /api/play/state.
    /// Matches the GameStateDTO returned by the Python backend.
    /// </summary>
    [Serializable]
    public class GameStateResponse
    {
        [JsonProperty("session_id")] public string sessionId;
        [JsonProperty("turn")] public int turn;
        [JsonProperty("phase")] public string phase;
        [JsonProperty("active_seat")] public int activeSeat;
        [JsonProperty("priority_seat")] public int prioritySeat;
        [JsonProperty("players")] public List<PlayerState> players;
        [JsonProperty("log")] public List<string> log;
        [JsonProperty("game_over")] public bool gameOver;
        [JsonProperty("winner_seat")] public int winnerSeat;

        public override string ToString() =>
            $"Turn {turn} | Phase: {phase} | Active: seat {activeSeat} | Over: {gameOver}";
    }

    [Serializable]
    public class PlayerState
    {
        [JsonProperty("seat")] public int seat;
        [JsonProperty("name")] public string name;
        [JsonProperty("life")] public int life;
        [JsonProperty("is_human")] public bool isHuman;
        [JsonProperty("eliminated")] public bool eliminated;
        [JsonProperty("hand_count")] public int handCount;
        [JsonProperty("library_count")] public int libraryCount;
        [JsonProperty("hand")] public List<BoardCard> hand;
        [JsonProperty("battlefield")] public List<BoardCard> battlefield;
        [JsonProperty("graveyard")] public List<BoardCard> graveyard;
        [JsonProperty("command_zone")] public List<BoardCard> commandZone;
        [JsonProperty("commander_tax")] public Dictionary<string, int> commanderTax;
        [JsonProperty("mana_available")] public int manaAvailable;

        public override string ToString() => $"{name} (Seat {seat}): {life} life";
    }

    [Serializable]
    public class BoardCard
    {
        [JsonProperty("id")] public int id;
        [JsonProperty("name")] public string name;
        [JsonProperty("type_line")] public string typeLine;
        [JsonProperty("cmc")] public int cmc;
        [JsonProperty("power")] public string power;
        [JsonProperty("toughness")] public string toughness;
        [JsonProperty("mana_cost")] public string manaCost;
        [JsonProperty("oracle_text")] public string oracleText;
        [JsonProperty("image_uri")] public string imageUri;
        [JsonProperty("tapped")] public bool tapped;
        [JsonProperty("is_commander")] public bool isCommander;
        [JsonProperty("is_creature")] public bool isCreature;
        [JsonProperty("owner_seat")] public int ownerSeat;

        public bool IsLand => typeLine != null && typeLine.ToLower().Contains("land");

        public override string ToString() => $"{name} (ID:{id}) [{typeLine}]";
    }

    [Serializable]
    public class LegalMove
    {
        [JsonProperty("action_type")] public string actionType;
        [JsonProperty("card_id")] public int? cardId;
        [JsonProperty("card_name")] public string cardName;
        [JsonProperty("description")] public string description;
    }

    [Serializable]
    public class ActionResult
    {
        [JsonProperty("result")] public string result;
        [JsonProperty("state")] public GameStateResponse state;
    }

    [Serializable]
    public class AITurnResult
    {
        [JsonProperty("actions")] public List<string> actions;
        [JsonProperty("state")] public GameStateResponse state;
    }

    [Serializable]
    public class PhaseResult
    {
        [JsonProperty("phase")] public string phase;
        [JsonProperty("state")] public GameStateResponse state;
    }

    // ── Request DTOs ───────────────────────────────────────────

    [Serializable]
    public class NewGameRequest
    {
        [JsonProperty("deck_ids")] public List<string> deckIds = new();
        [JsonProperty("player_names")] public List<string> playerNames =
            new() { "You", "AI-Aggro", "AI-Control", "AI-Combo" };
        [JsonProperty("human_seat")] public int humanSeat = 0;
    }

    [Serializable]
    public class PlayActionRequest
    {
        [JsonProperty("session_id")] public string sessionId;
        [JsonProperty("action_type")] public string actionType;
        [JsonProperty("card_id")] public int? cardId;
        [JsonProperty("target_seat")] public int? targetSeat;
    }
}
