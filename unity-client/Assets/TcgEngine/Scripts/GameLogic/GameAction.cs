
using Unity.Netcode;
using UnityEngine.Events;

namespace TcgEngine
{
    /// <summary>
    /// List of game actions and refreshes, that can be performed by the player or received
    /// </summary>

    public static class GameAction
    {
        public const ushort None = 0;

        //Commands (client to server)
        public const ushort PlayCard = 1000;
        public const ushort Attack = 1010;
        public const ushort AttackPlayer = 1012;
        public const ushort Move = 1015;
        public const ushort CastAbility = 1020;
        public const ushort SelectCard = 1030;
        public const ushort SelectPlayer = 1032;
        public const ushort SelectSlot = 1034;
        public const ushort SelectChoice = 1036;
        public const ushort SelectCost = 1037;
        public const ushort SelectMulligan = 1038;
        public const ushort CancelSelect = 1039;
        public const ushort EndTurn = 1040;
        public const ushort Resign = 1050;
        public const ushort ChatMessage = 1090;

        public const ushort PlayerSettings = 1100; //After connect, send player data
        public const ushort PlayerSettingsAI = 1102; //After connect, send player data
        public const ushort GameSettings = 1105; //After connect, send gameplay settings

        //Refresh (server to client)
        public const ushort Connected = 2000;
        public const ushort PlayerReady = 2001;

        public const ushort GameStart = 2010;
        public const ushort GameEnd = 2012;
        public const ushort NewTurn = 2015;

        public const ushort CardPlayed = 2020;
        public const ushort CardSummoned = 2022;
        public const ushort CardTransformed = 2023;
        public const ushort CardDiscarded = 2025;
        public const ushort CardDrawn = 2026;
        public const ushort CardMoved = 2027;

        public const ushort AttackStart = 2030;
        public const ushort AttackEnd = 2031;
        public const ushort AttackPlayerStart = 2032;
        public const ushort AttackPlayerEnd = 2033;
        public const ushort CardDamaged = 2036;
        public const ushort PlayerDamaged = 2037;
        public const ushort CardHealed = 2038;
        public const ushort PlayerHealed = 2039;

        public const ushort AbilityTrigger = 2040;
        public const ushort AbilityTargetCard = 2042;
        public const ushort AbilityTargetPlayer = 2043;
        public const ushort AbilityTargetSlot = 2044;
        public const ushort AbilityEnd = 2048;

        public const ushort SecretTriggered = 2060;
        public const ushort SecretResolved = 2061;
        public const ushort ValueRolled = 2070;

        public const ushort ServerMessage = 2190; //Server warning msg
        public const ushort RefreshAll = 2100;

        public static string GetString(ushort type)
        {
            if (type == GameAction.PlayCard)
                return "play";
            if (type == GameAction.Move)
                return "move";
            if (type == GameAction.Attack)
                return "attack";
            if (type == GameAction.AttackPlayer)
                return "attack_player";
            if (type == GameAction.CastAbility)
                return "cast_ability";
            if (type == GameAction.EndTurn)
                return "end_turn";
            if (type == GameAction.SelectCard)
                return "select_card";
            if (type == GameAction.SelectPlayer)
                return "select_player";
            if (type == GameAction.SelectChoice)
                return "select_choice";
            if (type == GameAction.SelectCost)
                return "select_cost";
            if (type == GameAction.SelectSlot)
                return "select_slot";
            if (type == GameAction.CancelSelect)
                return "cancel_select";
            if (type == GameAction.Resign)
                return "resign";
            if (type == GameAction.ChatMessage)
                return "chat";
            return type.ToString();
        }
    }
}