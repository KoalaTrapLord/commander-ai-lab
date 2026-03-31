using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Unity.Netcode;

namespace TcgEngine
{

    [System.Serializable]
    public enum GameType
    {
        Solo = 0,
        Adventure = 10,
        Multiplayer = 20,
        HostP2P = 30,
        Observer = 40,
    }

    [System.Serializable]
    public enum GameMode
    {
        Casual = 0,
        Ranked = 10,
    }

    /// <summary>
    /// Hold all client's game settings, like game mode, game uid and scene to load
    /// will be sent to server when a match start
    /// </summary>

    [System.Serializable]
    public class GameSettings : INetworkSerializable
    {
        public string server_url;   //Server to connect to
        public string game_uid;     //Game uid on that server
        public string scene;        //Which scene to load
        public int nb_players;      //How many players, including AI (UI only supports 2)

        public GameType game_type = GameType.Solo;      //Multiplayer? Solo? Observer?
        public GameMode game_mode = GameMode.Casual;    //Ranked or not? Other special game mode?
        public string level;                            //Adventure level ID

        public virtual bool IsHost()
        {
            return game_type == GameType.Solo || game_type == GameType.Adventure || game_type == GameType.HostP2P;
        }

        public virtual bool IsOffline()
        {
            return game_type == GameType.Solo || game_type == GameType.Adventure;
        }

        public virtual bool IsOnline()
        {
            return game_type == GameType.HostP2P || game_type == GameType.Multiplayer || game_type == GameType.Observer;
        }

        public virtual bool IsOnlinePlayer()
        {
            return game_type == GameType.HostP2P || game_type == GameType.Multiplayer;
        }

        public virtual bool IsRanked()
        {
            return game_mode == GameMode.Ranked;
        }

        public virtual string GetUrl()
        {
            if (!string.IsNullOrEmpty(server_url))
                return server_url;
            return NetworkData.Get().url;
        }

        public virtual string GetScene()
        {
            if (!string.IsNullOrEmpty(scene))
                return scene;
            return GameplayData.Get().GetRandomArena();
        }

        public virtual string GetGameModeId()
        {
            if (game_mode == GameMode.Ranked)
                return "ranked";
            if (game_mode == GameMode.Casual)
                return "casual";
            return "";
        }

        public virtual LevelData GetLevel()
        {
            if (game_type == GameType.Adventure)
            {
                return LevelData.Get(level);
            }
            return null;
        }

        public virtual void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref server_url);
            serializer.SerializeValue(ref game_uid);
            serializer.SerializeValue(ref scene);
            serializer.SerializeValue(ref game_type);
            serializer.SerializeValue(ref game_mode);
            serializer.SerializeValue(ref nb_players);
            serializer.SerializeValue(ref level);
        }

        public static string GetRankModeString(GameMode rank_mode)
        {
            if (rank_mode == GameMode.Ranked)
                return "ranked";
            if (rank_mode == GameMode.Casual)
                return "casual";
            return "";
        }

        public static GameMode GetRankMode(string rank_id)
        {
            if (rank_id == "ranked")
                return GameMode.Ranked;
            if (rank_id == "casual")
                return GameMode.Casual;
            return GameMode.Casual;
        }

        public static GameSettings Default
        {
            get
            {
                GameSettings settings = new GameSettings();
                settings.server_url = "";
                settings.game_uid = "test";
                settings.game_type = GameType.Solo;
                settings.game_mode = GameMode.Casual;
                settings.nb_players = 2;
                settings.scene = "Game";
                settings.level = "";
                return settings;
            }
        }

    }

    /// <summary>
    /// Hold all client's player settings, like avatar, cardback, and deck being used
    /// will be sent to server when a match start
    /// </summary>

    [System.Serializable]
    public class PlayerSettings : INetworkSerializable
    {
        public string username;
        public string avatar;
        public string cardback;
        public int ai_level;
        public UserDeckData deck = UserDeckData.Default;

        public bool HasDeck()
        {
            return deck != null && !string.IsNullOrEmpty(deck.tid);
        }

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref username);
            serializer.SerializeValue(ref avatar);
            serializer.SerializeValue(ref cardback);
            serializer.SerializeValue(ref ai_level);
            serializer.SerializeValue(ref deck);
        }

        public static PlayerSettings Default
        {
            get
            {
                PlayerSettings settings = new PlayerSettings();
                settings.username = "Player";
                settings.avatar = "";
                settings.cardback = "";
                settings.deck = UserDeckData.Default;
                settings.ai_level = 1;
                return settings;
            }
        }

        public static PlayerSettings DefaultAI
        {
            get
            {
                PlayerSettings settings = new PlayerSettings();
                settings.username = "AI";
                settings.avatar = "";
                settings.cardback = "";
                settings.deck = UserDeckData.Default;
                settings.ai_level = 10;
                return settings;
            }
        }

    }
}