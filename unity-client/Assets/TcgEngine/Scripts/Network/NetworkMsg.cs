
using Unity.Netcode;
using UnityEngine.Events;

namespace TcgEngine
{
    //-------- Connection --------

    public class MsgPlayerConnect : INetworkSerializable
    {
        public string user_id;
        public string username;
        public string game_uid;
        public int nb_players;
        public bool observer; //join as observer

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref user_id);
            serializer.SerializeValue(ref username);
            serializer.SerializeValue(ref game_uid);
            serializer.SerializeValue(ref nb_players);
            serializer.SerializeValue(ref observer);
        }
    }

    public class MsgAfterConnected : INetworkSerializable
    {
        public bool success;
        public int player_id;
        public Game game_data;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref success);
            serializer.SerializeValue(ref player_id);

            if (serializer.IsReader)
            {
                int size = 0;
                serializer.SerializeValue(ref size);
                if (size > 0)
                {
                    byte[] bytes = new byte[size];
                    serializer.SerializeValue(ref bytes);
                    game_data = NetworkTool.Deserialize<Game>(bytes);
                }
            }

            if (serializer.IsWriter)
            {
                byte[] bytes = NetworkTool.Serialize(game_data);
                int size = bytes.Length;
                serializer.SerializeValue(ref size);
                if(size > 0)
                    serializer.SerializeValue(ref bytes);
            }
        }
    }

    //-------- Matchmaking --------

    public class MsgMatchmaking : INetworkSerializable
    {
        public string user_id;
        public string username;
        public string group;
        public int players;
        public int elo;
        public bool refresh;
        public float time;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref user_id);
            serializer.SerializeValue(ref username);
            serializer.SerializeValue(ref group);
            serializer.SerializeValue(ref players);
            serializer.SerializeValue(ref elo);
            serializer.SerializeValue(ref refresh);
            serializer.SerializeValue(ref time);
        }
    }

    public class MatchmakingResult : INetworkSerializable
    {
        public bool success;
        public int players;
        public string group;
        public string server_url;
        public string game_uid;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref success);
            serializer.SerializeValue(ref players);
            serializer.SerializeValue(ref group);
            serializer.SerializeValue(ref server_url);
            serializer.SerializeValue(ref game_uid);
        }
    }

    public class MsgMatchmakingList : INetworkSerializable
    {
        public string username;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref username);
        }
    }

    [System.Serializable]
    public struct MatchmakingListItem : INetworkSerializable
    {
        public string group;
        public string user_id;
        public string username;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref group);
            serializer.SerializeValue(ref user_id);
            serializer.SerializeValue(ref username);
        }
    }

    public class MatchmakingList : INetworkSerializable
    {
        public MatchmakingListItem[] items;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            NetworkTool.NetSerializeArray(serializer, ref items);
        }
    }

    [System.Serializable]
    public class MatchListItem : INetworkSerializable
    {
        public string group;
        public string game_uid;
        public string game_url;
        public string[] usernames;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref group);
            serializer.SerializeValue(ref game_uid);
            serializer.SerializeValue(ref game_url);
            NetworkTool.NetSerializeArray(serializer, ref usernames);
        }
    }

    public class MatchList : INetworkSerializable
    {
        public MatchListItem[] items;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            NetworkTool.NetSerializeArray(serializer, ref items);
        }
    }

    //-------- In Game --------

    public class MsgPlayCard : INetworkSerializable
    {
        public string card_uid;
        public Slot slot;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref card_uid);
            serializer.SerializeNetworkSerializable(ref slot);
        }
    }

    public class MsgCard : INetworkSerializable
    {
        public string card_uid;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref card_uid);
        }
    }

    public class MsgCardValue : INetworkSerializable
    {
        public string card_uid;
        public int value;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref card_uid);
            serializer.SerializeValue(ref value);
        }
    }

    public class MsgPlayer : INetworkSerializable
    {
        public int player_id;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref player_id);
        }
    }

    public class MsgPlayerValue : INetworkSerializable
    {
        public int player_id;
        public int value;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref player_id);
            serializer.SerializeValue(ref value);
        }
    }

    public class MsgAttack : INetworkSerializable
    {
        public string attacker_uid;
        public string target_uid;
        public int damage;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref attacker_uid);
            serializer.SerializeValue(ref target_uid);
            serializer.SerializeValue(ref damage);
        }
    }

    public class MsgAttackPlayer : INetworkSerializable
    {
        public string attacker_uid;
        public int target_id;
        public int damage;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref attacker_uid);
            serializer.SerializeValue(ref target_id);
            serializer.SerializeValue(ref damage);
        }
    }

    public class MsgCastAbility : INetworkSerializable
    {
        public string ability_id;
        public string caster_uid;
        public string target_uid;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref ability_id);
            serializer.SerializeValue(ref caster_uid);
            serializer.SerializeValue(ref target_uid);
        }
    }

    public class MsgCastAbilityPlayer : INetworkSerializable
    {
        public string ability_id;
        public string caster_uid;
        public int target_id;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref ability_id);
            serializer.SerializeValue(ref caster_uid);
            serializer.SerializeValue(ref target_id);
        }
    }

    public class MsgCastAbilitySlot : INetworkSerializable
    {
        public string ability_id;
        public string caster_uid;
        public Slot slot;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref ability_id);
            serializer.SerializeValue(ref caster_uid);
            serializer.SerializeNetworkSerializable(ref slot);
        }
    }

    public class MsgSecret : INetworkSerializable
    {
        public string secret_uid;
        public string triggerer_uid;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref secret_uid);
            serializer.SerializeValue(ref triggerer_uid);
        }
    }

    public class MsgMulligan : INetworkSerializable
    {
        public string[] cards;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            NetworkTool.NetSerializeArray(serializer, ref cards);
        }
    }

    public class MsgInt : INetworkSerializable
    {
        public int value;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref value);
        }
    }

    public class MsgChat : INetworkSerializable
    {
        public int player_id;
        public string msg;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            serializer.SerializeValue(ref player_id);
            serializer.SerializeValue(ref msg);
        }
    }

    public class MsgRefreshAll : INetworkSerializable
    {
        public Game game_data;

        public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
        {
            if (serializer.IsReader)
            {
                int size = 0;
                serializer.SerializeValue(ref size);
                if (size > 0)
                {
                    byte[] bytes = new byte[size];
                    serializer.SerializeValue(ref bytes);
                    game_data = NetworkTool.Deserialize<Game>(bytes);
                }
            }

            if (serializer.IsWriter)
            {
                byte[] bytes = NetworkTool.Serialize(game_data);
                int size = bytes.Length;
                serializer.SerializeValue(ref size);
                if (size > 0)
                    serializer.SerializeValue(ref bytes);
            }
        }
    }

}