using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace CommanderAILab.Models
{
    /// <summary>Maps to StartResponse from /api/lab/start.</summary>
    [Serializable]
    public class SimStartResponse
    {
        [JsonProperty("batchId")] public string batchId;
        [JsonProperty("status")] public string status;
        [JsonProperty("message")] public string message;

        public override string ToString() => $"Batch {batchId}: {status}";
    }

    /// <summary>Maps to StatusResponse from /api/lab/status/{id}.</summary>
    [Serializable]
    public class SimStatusModel
    {
        [JsonProperty("batchId")] public string batchId;
        [JsonProperty("running")] public bool running;
        [JsonProperty("completed")] public int completed;
        [JsonProperty("total")] public int total;
        [JsonProperty("threads")] public int threads;
        [JsonProperty("elapsedMs")] public int elapsedMs;
        [JsonProperty("error")] public string error;
        [JsonProperty("simsPerSec")] public float simsPerSec;
        [JsonProperty("run_id")] public string runId;
        [JsonProperty("games_completed")] public int gamesCompleted;
        [JsonProperty("total_games")] public int totalGames;
        [JsonProperty("current_decks")] public List<string> currentDecks;

        public override string ToString() => $"Batch {batchId}: {completed}/{total} ({(running ? "running" : "done")})";
    }
}
