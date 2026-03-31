using System.Collections;
using System.Collections.Generic;
using TcgEngine.Client;
using UnityEngine;

namespace TcgEngine.UI
{
    /// <summary>
    /// History bar shows all the previous moved perform by a player this turn
    /// </summary>

    public class TurnHistoryBar : MonoBehaviour
    {
        public bool is_opponent;
        public TurnHistoryLine[] history_lines;

        void Start()
        {

        }

        void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            int player_id = is_opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
            Game data = GameClient.Get().GetGameData();
            Player player = data.GetPlayer(player_id);

            if (player != null && player.history_list != null)
            {
                int index = 0;
                foreach (ActionHistory order in player.history_list)
                {
                    if (index < history_lines.Length)
                    {
                        history_lines[index].SetLine(order);
                        index++;
                    }
                }

                while (index < history_lines.Length)
                {
                    history_lines[index].Hide();
                    index++;
                }
            }
        }
    }
}
