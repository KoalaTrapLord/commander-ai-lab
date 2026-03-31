using System;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// List of data structure used by the ApiClient requests and responses
    /// </summary>

    //--------- Requests -----------

    [Serializable]
    public struct LoginRequest
    {
        public string email;
        public string username;
        public string password;
    }

    [Serializable]
    public struct AutoLoginRequest
    {
        public string refresh_token;
    }

    [Serializable]
    public struct RegisterRequest
    {
        public string email;
        public string username;
        public string password;
        public string avatar;
    }

    [Serializable]
    public struct EditUserRequest
    {
        public string avatar;
        public string cardback;
    }

    [Serializable]
    public struct EditEmailRequest
    {
        public string email;
    }

    [Serializable]
    public struct EditPasswordRequest
    {
        public string password_previous;
        public string password_new;
    }

    [Serializable]
    public struct FriendAddRequest
    {
        public string username;
    }

    [Serializable]
    public struct AddMatchRequest
    {
        public string tid;
        public string[] players;
        public string mode;
        public bool ranked;
    }

    [Serializable]
    public struct CompleteMatchRequest
    {
        public string tid;
        public string winner;
    }

    [Serializable]
    public struct RewardGainRequest
    {
        public string reward;
    }

    [Serializable]
    public struct BuyPackRequest
    {
        public string pack;
        public int quantity;
    }

    [Serializable]
    public struct BuyCardRequest
    {
        public string card;
        public string variant;
        public int quantity;
    }

    [Serializable]
    public struct SellDuplicateRequest
    {
        //public string variant;
        //public string rarity;
        public int keep;
    }

    [Serializable]
    public struct OpenPackRequest
    {
        public string pack;
    }

    //--------- Response -----------

    [Serializable]
    public struct VersionResponse
    {
        public string version;
    }

    [Serializable]
    public struct RegisterResponse
    {
        public string id;
        public string username;
        public string version;
        public bool success;
        public string error;
    }

    [Serializable]
    public struct LoginResponse
    {
        public string id;
        public string username;
        public string refresh_token;
        public string access_token;
        public int permission_level;
        public int validation_level;
        public int duration;
        public string version;
        public string error;
        public bool success;
    }

    [Serializable]
    public struct UserIdResponse
    {
        public string id;
        public string username;
        public string error;
    }

    [Serializable]
    public struct MatchResponse
    {
        public string tid;
        public string[] players;
        public DateTime start;
        public DateTime end;
        public string winner;
        public bool completed;
        public MatchDataResponse[] udata;
    }

    [Serializable]
    public struct MatchDataResponse
    {
        public string username;
        public int rank;
        public DeckData deck;
        public RewardResponse reward;
    }

    [Serializable]
    public struct RewardResponse
    {
        public string tid;
        public int coins;
        public int elo;
        public int xp;
        public string[] cards;
        public string[] decks;
    }

    [Serializable]
    public struct MarketResponse
    {
        public string seller;
        public string card;
        public int price;
        public int quantity;
    }

    [Serializable]
    public struct FriendResponse
    {
        public string username;
        public string server_time;
        public FriendData[] friends;
        public FriendData[] friends_requests;
    }

    [System.Serializable]
    public struct FriendData
    {
        public string username;
        public string avatar;
        public string last_online_time;
    }

}
