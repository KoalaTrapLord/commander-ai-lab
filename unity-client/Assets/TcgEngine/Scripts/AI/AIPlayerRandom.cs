using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TcgEngine.Client;
using TcgEngine.Gameplay;

namespace TcgEngine.AI
{
    /// <summary>
    /// AI player making completely random decisions, really bad AI but useful for testing
    /// </summary>
    
    public class AIPlayerRandom : AIPlayer
    {
        private bool is_playing = false;
        private bool is_selecting = false;

        private System.Random rand = new System.Random();

        public AIPlayerRandom(GameLogic gameplay, int id, int level)
        {
            this.gameplay = gameplay;
            player_id = id;
        }

        public override void Update()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            Player player = game_data.GetPlayer(player_id);

            if (game_data.IsPlayerTurn(player) && !gameplay.IsResolving())
            {
                if(!is_playing && game_data.selector == SelectorType.None && game_data.current_player == player_id)
                {
                    is_playing = true;
                    TimeTool.StartCoroutine(AiTurn());
                }

                if (!is_selecting && game_data.selector != SelectorType.None && game_data.selector_player_id == player_id)
                {
                    if (game_data.selector == SelectorType.SelectTarget)
                    {
                        //AI select target
                        is_selecting = true;
                        TimeTool.StartCoroutine(AiSelectTarget());
                    }

                    if (game_data.selector == SelectorType.SelectorCard)
                    {
                        //AI select target
                        is_selecting = true;
                        TimeTool.StartCoroutine(AiSelectCard());
                    }

                    if (game_data.selector == SelectorType.SelectorChoice)
                    {
                        //AI select target
                        is_selecting = true;
                        TimeTool.StartCoroutine(AiSelectChoice());
                    }

                    if (game_data.selector == SelectorType.SelectorCost)
                    {
                        //AI select target
                        is_selecting = true;
                        TimeTool.StartCoroutine(AiSelectCost());
                    }
                }

            }

            if (!is_selecting && game_data.IsPlayerMulliganTurn(player))
            {
                is_selecting = true;
                TimeTool.StartCoroutine(AiSelectMulligan());
            }
        }

        private IEnumerator AiTurn()
        {
            yield return new WaitForSeconds(1f);

            PlayCard();

            yield return new WaitForSeconds(0.5f);

            PlayCard();

            yield return new WaitForSeconds(0.5f);

            PlayCard();

            yield return new WaitForSeconds(0.5f);

            Attack();

            yield return new WaitForSeconds(0.5f);

            Attack();

            yield return new WaitForSeconds(0.5f);

            AttackPlayer();

            yield return new WaitForSeconds(0.5f);

            EndTurn();

            is_playing = false;
        }

        private IEnumerator AiSelectCard()
        {
            yield return new WaitForSeconds(0.5f);

            SelectCard();

            yield return new WaitForSeconds(0.5f);

            CancelSelect();
            is_selecting = false;
        }

        private IEnumerator AiSelectTarget()
        {
            yield return new WaitForSeconds(0.5f);

            SelectTarget();

            yield return new WaitForSeconds(0.5f);

            CancelSelect();
            is_selecting = false;
        }

        private IEnumerator AiSelectChoice()
        {
            yield return new WaitForSeconds(0.5f);

            SelectChoice();

            yield return new WaitForSeconds(0.5f);

            CancelSelect();
            is_selecting = false;
        }

        private IEnumerator AiSelectCost()
        {
            yield return new WaitForSeconds(0.5f);

            SelectCost();

            yield return new WaitForSeconds(0.5f);

            CancelSelect();
            is_selecting = false;
        }

        private IEnumerator AiSelectMulligan()
        {
            yield return new WaitForSeconds(0.5f);

            SelectMulligan();

            yield return new WaitForSeconds(0.5f);
            is_selecting = false;
        }

        //----------

        public void PlayCard()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            Player player = game_data.GetPlayer(player_id);
            if (player.cards_hand.Count > 0 && game_data.IsPlayerActionTurn(player))
            {
                Card random = player.GetRandomCard(player.cards_hand, rand);
                Slot slot = player.GetRandomEmptySlot(rand);

                if (random != null && random.CardData.IsRequireTargetSpell())
                    slot = game_data.GetRandomSlot(rand); //Spell can target any slot, not just your side

                if(random != null && random.CardData.IsEquipment())
                    slot = player.GetRandomOccupiedSlot(rand);

                if (random != null)
                    gameplay.PlayCard(random, slot);
            }
        }

        public void Attack()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            Player player = game_data.GetPlayer(player_id);
            if (player.cards_board.Count > 0 && game_data.IsPlayerActionTurn(player))
            {
                Card random = player.GetRandomCard(player.cards_board, rand);
                Card rtarget = game_data.GetRandomBoardCard(rand);
                if (random != null && rtarget != null)
                    gameplay.AttackTarget(random, rtarget);
            }
        }

        public void AttackPlayer()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            Player player = game_data.GetPlayer(player_id);
            Player oplayer = game_data.GetRandomPlayer(rand);
            if (player.cards_board.Count > 0 && game_data.IsPlayerActionTurn(player))
            {
                Card random = player.GetRandomCard(player.cards_board, rand);
                if (random != null && oplayer != null && oplayer != player)
                    gameplay.AttackPlayer(random, oplayer);
            }
        }

        public void SelectCard()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            Player player = game_data.GetPlayer(player_id);
            AbilityData ability = AbilityData.Get(game_data.selector_ability_id);
            Card caster = game_data.GetCard(game_data.selector_caster_uid);
            if (player != null && ability != null && caster != null)
            {
                List<Card> card_list = ability.GetCardTargets(game_data, caster);
                if (card_list.Count > 0)
                {
                    Card card = card_list[rand.Next(0, card_list.Count)];
                    gameplay.SelectCard(card);
                }
            }
        }

        public void SelectTarget()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            if (game_data.selector != SelectorType.None)
            {
                int target_player = player_id;
                AbilityData ability = AbilityData.Get(game_data.selector_ability_id);
                if (ability != null && ability.target == AbilityTarget.SelectTarget)
                    target_player = (player_id == 0 ? 1 : 0);

                Player tplayer = game_data.GetPlayer(target_player);
                if (tplayer.cards_board.Count > 0)
                {
                    Card random = tplayer.GetRandomCard(tplayer.cards_board, rand);
                    if (random != null)
                        gameplay.SelectCard(random);
                }
            }
        }

        public void SelectChoice()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            if (game_data.selector != SelectorType.None)
            {
                AbilityData ability = AbilityData.Get(game_data.selector_ability_id);
                if (ability != null && ability.chain_abilities.Length > 0)
                {
                    int choice = rand.Next(0, ability.chain_abilities.Length);
                    gameplay.SelectChoice(choice);
                }
            }
        }

        public void SelectCost()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            if (game_data.selector != SelectorType.None)
            {
                Player player = game_data.GetPlayer(player_id);
                Card card = game_data.GetCard(game_data.selector_caster_uid);
                if (player != null && card != null)
                {
                    int max = Mathf.Clamp(player.mana, 0, 9);
                    int choice = rand.Next(0, max + 1);
                    gameplay.SelectCost(choice);
                }
            }
        }

        public void CancelSelect()
        {
            if (CanPlay())
            {
                gameplay.CancelSelection();
            }
        }

        public void SelectMulligan()
        {
            if (!CanPlay())
                return;

            Game game_data = gameplay.GetGameData();
            if (game_data.phase == GamePhase.Mulligan)
            {
                Player player = game_data.GetPlayer(player_id);
                string[] cards = new string[0]; //Don't mulligan
                gameplay.Mulligan(player, cards);
            }
        }

        public void EndTurn()
        {
            if (CanPlay())
            {
                gameplay.EndTurn();
            }
        }
    }

}