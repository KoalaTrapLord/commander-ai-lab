using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Gameplay;

namespace TcgEngine.AI
{
    /// <summary>
    /// AI player base class, other AI inherit from this
    /// </summary>

    public abstract class AIPlayer 
    {
        public int player_id;
        public int ai_level;

        protected GameLogic gameplay;

        public virtual void Update()
        {
            //Script called by game server to update AI
            //Override this to let the AI play
        }

        public bool CanPlay()
        {
            Game game_data = gameplay.GetGameData();
            Player player = game_data.GetPlayer(player_id);
            bool can_play = game_data.IsPlayerTurn(player) || game_data.IsPlayerMulliganTurn(player);
            return can_play && !gameplay.IsResolving();
        }

        public static AIPlayer Create(AIType type, GameLogic gameplay, int id, int level = 0)
        {
            if (type == AIType.Random)
                return new AIPlayerRandom(gameplay, id, level);
            if (type == AIType.MiniMax)
                return new AIPlayerMM(gameplay, id, level);
            return null;
        }
    }

    public enum AIType
    {
        Random = 0,      //Dumb AI that just do random moves, useful for testing cards without getting destroyed
        MiniMax = 10,    //Stronger AI using Minimax algo with alpha-beta pruning
    }
}
