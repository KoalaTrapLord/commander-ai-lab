using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine.AI
{
    /// <summary>
    /// Values and calculations for various values of the AI decision-making, adjusting these can improve your AI
    /// Heuristic: Represent the score of a board state, high score favor AI, low score favor the opponent
    /// Action Score: Represent the score of an individual action, to proritize actions if too many in a single node
    /// Action Sort Order: Value to determine the order actions should be executed in a single turn to avoid searching same things in different order, executed in ascending order
    /// </summary>

    public class AIHeuristic
    {
        //---------- Heuristic PARAMS -------------

        public int board_card_value = 20;       //Score of having cards on board
        public int secret_card_value = 10;       //Score of having cards in secret zone
        public int hand_card_value = 5;         //Score of having cards in hand
        public int kill_value = 5;              //Score of killing a card

        public int player_hp_value = 4;         //Score per player hp
        public int card_attack_value = 3;       //Score per board card attack
        public int card_hp_value = 2;           //Score per board card hp
        public int card_status_value = 15;       //Score per status on card (multiplied by hvalue of StatusData)

        //-----------

        private int ai_player_id;           //ID of this AI, usually the human is 0 and AI is 1
        private int ai_level;               //ai level (level 10 is the best, level 1 is the worst)
        private int heuristic_modifier;     //Randomize heuristic for lower level ai
        private System.Random random_gen;

        public AIHeuristic(int player_id, int level)
        {
            ai_player_id = player_id;
            ai_level = level;
            heuristic_modifier = GetHeuristicModifier();
            random_gen = new System.Random();
        }

        public int CalculateHeuristic(Game data, NodeState node)
        {
            Player aiplayer = data.GetPlayer(ai_player_id);
            Player oplayer = data.GetOpponentPlayer(ai_player_id);
            return CalculateHeuristic(data, node, aiplayer, oplayer);
        }

        //Calculate full heuristic
        //Should return a value between -10000 and 10000 (unless its a win)
        public int CalculateHeuristic(Game data, NodeState node, Player aiplayer, Player oplayer)
        {
            int score = 0;

            //Victories
            if (aiplayer.IsDead())
                score += -100000 + node.tdepth * 1000; //Add node depth to seek surviving longest
            if (oplayer.IsDead())
                score += 100000 - node.tdepth * 1000; //Reduce node depth to seek fastest win

            //Board state
            score += aiplayer.cards_board.Count * board_card_value;
            score += aiplayer.cards_equip.Count * board_card_value;
            score += aiplayer.cards_secret.Count * secret_card_value;
            score += aiplayer.cards_hand.Count * hand_card_value;
            score += aiplayer.kill_count * kill_value;
            score += aiplayer.hp * player_hp_value;

            score -= oplayer.cards_board.Count * board_card_value;
            score -= oplayer.cards_equip.Count * board_card_value;
            score -= oplayer.cards_secret.Count * secret_card_value;
            score -= oplayer.cards_hand.Count * hand_card_value;
            score -= oplayer.kill_count * kill_value;
            score -= oplayer.hp * player_hp_value;


            foreach (Card card in aiplayer.cards_board)
            {
                score += card.GetAttack() * card_attack_value;
                score += card.GetHP() * card_hp_value;

                foreach (CardStatus status in card.status)
                    score += status.StatusData.hvalue * card_status_value;
                foreach (CardStatus status in card.ongoing_status)
                    score += status.StatusData.hvalue * card_status_value;
            }
            foreach (Card card in oplayer.cards_board)
            {
                score -= card.GetAttack() * card_attack_value;
                score -= card.GetHP() * card_hp_value;

                foreach (CardStatus status in card.status)
                    score -= status.StatusData.hvalue * card_status_value;
                foreach (CardStatus status in card.ongoing_status)
                    score -= status.StatusData.hvalue * card_status_value;
            }

            if (heuristic_modifier > 0)
                score += random_gen.Next(-heuristic_modifier, heuristic_modifier);

            return score;
        }

        //This calculates the score of an individual action, instead of the board state
        //When too many actions are possible in a single node, only the ones with best action score will be evaluated
        //Make sure to return a positive value
        public int CalculateActionScore(Game data, AIAction order)
        {
            if (order.type == GameAction.EndTurn)
                return 0; //Other orders are better

            if (order.type == GameAction.CancelSelect)
                return 0; //Other orders are better

            if (order.type == GameAction.CastAbility)
            {
                return 200;
            }

            if (order.type == GameAction.Attack)
            {
                Card card = data.GetCard(order.card_uid);
                Card target = data.GetCard(order.target_uid);
                int ascore = card.GetAttack() >= target.GetHP() ? 300 : 100; //Are you killing the card?
                int oscore = target.GetAttack() >= card.GetHP() ? -200 : 0; //Are you getting killed?
                return ascore + oscore + target.GetAttack() * 5;            //Always better to get rid of high-attack cards
            }
            if (order.type == GameAction.AttackPlayer)
            {
                Card card = data.GetCard(order.card_uid);
                Player player = data.GetPlayer(order.target_player_id);
                int ascore = card.GetAttack() >= player.hp ? 500 : 200;     //Are you killing the player?
                return ascore + (card.GetAttack() * 10) - player.hp;        //Always better to inflict more damage
            }
            if (order.type == GameAction.PlayCard)
            {
                Player player = data.GetPlayer(ai_player_id);
                Card card = data.GetCard(order.card_uid);
                if (card.CardData.IsBoardCard())
                    return 200 + (card.GetMana() * 5) - (30 * player.cards_board.Count); //High cost cards are better to play, better to play when not a lot of cards in play
                else if (card.CardData.IsEquipment())
                    return 200 + (card.GetMana() * 5) - (30 * player.cards_equip.Count);
                else
                    return 200 + (card.GetMana() * 5);
            }

            if (order.type == GameAction.Move)
            {
                return 100;
            }

            return 100; //Other actions are better than End/Cancel
        }

        //Within the same turn, actions can only be executed in sorting order, make sure it returns positive value higher than 0 or it wont be sorted
        //This prevents calculating all possibilities of A->B->C  B->C->A   C->A->B  etc..
        //If two AIActions with same sorting value, or if sorting value is 0, ai will test all ordering variations (slower)
        //This would not be necessary in a game with only 1 action per turn (such as chess) but is useful for AI that can perform multiple actions in 1 turn
        //Ordering could be improved, pretty much random now
        public int CalculateActionSort(Game data, AIAction order)
        {
            if (order.type == GameAction.EndTurn)
                return 0; //End turn can always be performed, 0 means any order
            if (data.selector != SelectorType.None)
                return 0; //Selector actions not affected by sorting

            Card card = data.GetCard(order.card_uid);
            Card target = order.target_uid != null ? data.GetCard(order.target_uid) : null;
            bool is_spell = card != null && !card.CardData.IsBoardCard();

            int type_sort = 0;
            if (order.type == GameAction.PlayCard && is_spell)
                type_sort = 1; //Play Spells first
            if (order.type == GameAction.CastAbility)
                type_sort = 2; //Card Abilities second
            if (order.type == GameAction.Move)
                type_sort = 3; //Move third
            if (order.type == GameAction.Attack)
                type_sort = 4; //Attacks fourth
            if (order.type == GameAction.AttackPlayer)
                type_sort = 5; //Player attacks fifth
            if (order.type == GameAction.PlayCard && !is_spell)
                type_sort = 7; //Play Characters last

            int card_sort = card != null ? (card.Hash % 100) : 0;
            int target_sort = target != null ? (target.Hash % 100) : 0;
            int sort = type_sort * 10000 + card_sort * 100 + target_sort + 1;
            return sort;
        }

        //Lower level AI add a random number to their heuristic
        private int GetHeuristicModifier()
        {
            if (ai_level >= 10)
                return 0;
            if (ai_level == 9)
                return 5;
            if (ai_level == 8)
                return 10;
            if (ai_level == 7)
                return 20;
            if (ai_level == 6)
                return 30;
            if (ai_level == 5)
                return 40;
            if (ai_level == 4)
                return 50;
            if (ai_level == 3)
                return 75;
            if (ai_level == 2)
                return 100;
            if (ai_level <= 1)
                return 200;
            return 0;
        }

        //Check if this node represent one of the players winning
        public bool IsWin(NodeState node)
        {
            return node.hvalue > 50000 || node.hvalue < -50000;
        }

    }
}
