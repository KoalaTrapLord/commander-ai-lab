using System.Collections.Generic;
using TcgEngine.AI;
using TcgEngine.Gameplay;
using Unity.Netcode;
using UnityEngine;
using UnityEngine.Events;

namespace TcgEngine.Server
{
    /// <summary>
    /// Represent one game on the server, when playing solo this will be created locally, 
    /// or if online multiple GameServer, one for each match, will be created by the dedicated server
    /// Manage receiving actions, sending refresh, and running AI
    /// </summary>

    public class GameServer
    {
        public string game_uid; //Game unique ID
        public int nb_players = 2;

        public static float game_expire_time = 30f;      //How long for the game to be deleted when no one is connected
        public static float win_expire_time = 60f;       //How long for a player to be declared winnner if hes the only one connected

        private Game game_data;
        private GameLogic gameplay;
        private float expiration = 0f;
        private float win_expiration = 0f;
        private bool is_dedicated_server = false;

        private List<ClientData> players = new List<ClientData>();            //Exclude observers, stays in array when disconnected, only players can send commands
        private List<ClientData> connected_clients = new List<ClientData>();  //Include obervers, removed from array when disconnected, all clients receive refreshes
        private List<AIPlayer> ai_list = new List<AIPlayer>();                //List of all AI players
        private Queue<QueuedGameAction> queued_actions = new Queue<QueuedGameAction>(); //List of action waiting to be processed
        
        private Dictionary<ushort, CommandEvent> registered_commands = new Dictionary<ushort, CommandEvent>();

        public GameServer(string uid, int players, bool online)
        {
            Init(uid, players, online);
        }

        ~GameServer()
        {
            Clear();
        }

        protected virtual void Init(string uid, int players, bool online)
        {
            game_uid = uid;
            nb_players = Mathf.Max(players, 2);
            is_dedicated_server = online;
            game_data = new Game(uid, nb_players);
            gameplay = new GameLogic(game_data);

            //Commands
            RegisterAction(GameAction.PlayerSettings, ReceivePlayerSettings);
            RegisterAction(GameAction.PlayerSettingsAI, ReceivePlayerSettingsAI);
            RegisterAction(GameAction.GameSettings, ReceiveGameplaySettings);
            RegisterAction(GameAction.PlayCard, ReceivePlayCard);
            RegisterAction(GameAction.Attack, ReceiveAttackTarget);
            RegisterAction(GameAction.AttackPlayer, ReceiveAttackPlayer);
            RegisterAction(GameAction.Move, ReceiveMove);
            RegisterAction(GameAction.CastAbility, ReceiveCastCardAbility);
            RegisterAction(GameAction.SelectCard, ReceiveSelectCard);
            RegisterAction(GameAction.SelectPlayer, ReceiveSelectPlayer);
            RegisterAction(GameAction.SelectSlot, ReceiveSelectSlot);
            RegisterAction(GameAction.SelectChoice, ReceiveSelectChoice);
            RegisterAction(GameAction.SelectCost, ReceiveSelectCost);
            RegisterAction(GameAction.SelectMulligan, ReceiveSelectMulligan);
            RegisterAction(GameAction.CancelSelect, ReceiveCancelSelection);
            RegisterAction(GameAction.EndTurn, ReceiveEndTurn);
            RegisterAction(GameAction.Resign, ReceiveResign);
            RegisterAction(GameAction.ChatMessage, ReceiveChat);

            //Events
            gameplay.onGameStart += OnGameStart;
            gameplay.onGameEnd += OnGameEnd;
            gameplay.onTurnStart += OnTurnStart;
            gameplay.onRefresh += RefreshAll;

            gameplay.onCardPlayed += OnCardPlayed;
            gameplay.onCardSummoned += OnCardSummoned;
            gameplay.onCardMoved += OnCardMoved;
            gameplay.onCardTransformed += OnCardTransformed;
            gameplay.onCardDiscarded += OnCardDiscarded;
            gameplay.onCardDrawn += OnCardDraw;
            gameplay.onRollValue += OnValueRolled;

            gameplay.onAbilityStart += OnAbilityStart;
            gameplay.onAbilityTargetCard += OnAbilityTargetCard;
            gameplay.onAbilityTargetPlayer += OnAbilityTargetPlayer;
            gameplay.onAbilityTargetSlot += OnAbilityTargetSlot;
            gameplay.onAbilityEnd += OnAbilityEnd;

            gameplay.onAttackStart += OnAttackStart;
            gameplay.onAttackEnd += OnAttackEnd;
            gameplay.onAttackPlayerStart += OnAttackPlayerStart;
            gameplay.onAttackPlayerEnd += OnAttackPlayerEnd;

            gameplay.onCardDamaged += OnCardDamaged;
            gameplay.onPlayerDamaged += OnPlayerDamaged;
            gameplay.onCardHealed += OnCardHealed;
            gameplay.onPlayerHealed += OnPlayerHealed ;

            gameplay.onSecretTrigger += OnSecretTriggered;
            gameplay.onSecretResolve += OnSecretResolved;
        }

        protected virtual void Clear()
        {
            gameplay.onGameStart -= OnGameStart;
            gameplay.onGameEnd -= OnGameEnd;
            gameplay.onTurnStart -= OnTurnStart;
            gameplay.onRefresh -= RefreshAll;

            gameplay.onCardPlayed -= OnCardPlayed;
            gameplay.onCardSummoned -= OnCardSummoned;
            gameplay.onCardMoved -= OnCardMoved;
            gameplay.onCardTransformed -= OnCardTransformed;
            gameplay.onCardDiscarded -= OnCardDiscarded;
            gameplay.onCardDrawn -= OnCardDraw;
            gameplay.onRollValue -= OnValueRolled;

            gameplay.onAbilityStart -= OnAbilityStart;
            gameplay.onAbilityTargetCard -= OnAbilityTargetCard;
            gameplay.onAbilityTargetPlayer -= OnAbilityTargetPlayer;
            gameplay.onAbilityTargetSlot -= OnAbilityTargetSlot;
            gameplay.onAbilityEnd -= OnAbilityEnd;

            gameplay.onAttackStart -= OnAttackStart;
            gameplay.onAttackEnd -= OnAttackEnd;
            gameplay.onAttackPlayerStart -= OnAttackPlayerStart;
            gameplay.onAttackPlayerEnd -= OnAttackPlayerEnd;
            gameplay.onCardDamaged -= OnCardDamaged;
            gameplay.onPlayerDamaged -= OnPlayerDamaged;

            gameplay.onSecretTrigger -= OnSecretTriggered;
            gameplay.onSecretResolve -= OnSecretResolved;
        }

        public virtual void Update()
        {
            //Game Expiration if no one is connected or game ended
            int connected_players = CountConnectedClients();
            if (HasGameEnded() || connected_players == 0)
                expiration += Time.deltaTime;

            //Win expiration if all other players left
            if (connected_players == 1 && HasGameStarted() && !HasGameEnded())
                win_expiration += Time.deltaTime;

            if (is_dedicated_server && !HasGameEnded() && IsWinExpired())
                EndExpiredGame();

            //Timer during game
            if (game_data.state == GameState.Play && !gameplay.IsResolving())
            {
                game_data.turn_timer -= Time.deltaTime;
                if (game_data.turn_timer <= 0f)
                {
                    //Time expired during turn
                    gameplay.NextStep();
                }
            }

            //Start Game when ready
            if (game_data.state == GameState.Connecting)
            {
                bool all_connected = game_data.AreAllPlayersConnected();
                bool all_ready = game_data.AreAllPlayersReady();
                if (all_connected && all_ready)
                {
                    StartGame();
                }
            }

            //Process queued actions
            if (queued_actions.Count > 0 && !gameplay.IsResolving())
            {
                QueuedGameAction action = queued_actions.Dequeue();
                ExecuteAction(action.type, action.client, action.sdata);
            }

            //Update game logic
            gameplay.Update(Time.deltaTime);

            //Update AI
            foreach (AIPlayer ai in ai_list)
            {
                ai.Update();
            }
        }

        protected virtual void StartGame()
        {
            //Setup AI
            bool ai_vs_ai = !is_dedicated_server && GameplayData.Get().ai_vs_ai;
            foreach (Player player in game_data.players)
            {
                if (player.is_ai || ai_vs_ai)
                {
                    AIPlayer ai_gameplay = AIPlayer.Create(GameplayData.Get().ai_type, gameplay, player.player_id, player.ai_level);
                    ai_list.Add(ai_gameplay);
                }
            }

            //Start Game
            gameplay.StartGame();
        }

        //End game when it has expired (only one player is still connected)
        protected virtual void EndExpiredGame()
        {
            Game gdata = gameplay.GetGameData();
            foreach (Player player in gdata.players)
            {
                if (player.IsConnected())
                {
                    gameplay.EndGame(player.player_id);
                    return;
                }
            }
        }

        //------ Receive Actions -------

        private void RegisterAction(ushort tag, UnityAction<ClientData, SerializedData> callback)
        {
            CommandEvent cmdevt = new CommandEvent();
            cmdevt.tag = tag;
            cmdevt.callback = callback;
            registered_commands.Add(tag, cmdevt);
        }

        public void ReceiveAction(ulong client_id, FastBufferReader reader)
        {
            ClientData client = GetClient(client_id);
            if (client != null)
            {
                reader.ReadValueSafe(out ushort type);
                SerializedData sdata = new SerializedData(reader);
                if (!gameplay.IsResolving())
                {
                    //Not resolving, execute now
                    ExecuteAction(type, client, sdata);
                }
                else
                {
                    //Resolving, wait before executing
                    QueuedGameAction action = new QueuedGameAction();
                    action.type = type;
                    action.client = client;
                    action.sdata = sdata;
                    sdata.PreRead();
                    queued_actions.Enqueue(action);
                }
            }
        }

        public void ExecuteAction(ushort type, ClientData client, SerializedData sdata)
        {
            bool found = registered_commands.TryGetValue(type, out CommandEvent command);
            if(found)
                command.callback.Invoke(client, sdata);
        }

        //-------

        public void ReceivePlayerSettings(ClientData iclient, SerializedData sdata)
        {
            PlayerSettings msg = sdata.Get<PlayerSettings>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null)
            {
                SetPlayerSettings(player.player_id, msg);
            }
        }

        public void ReceivePlayerSettingsAI(ClientData iclient, SerializedData sdata)
        {
            PlayerSettings msg = sdata.Get<PlayerSettings>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null)
            {
                SetPlayerSettingsAI(player.player_id, msg);
            }
        }

        public void ReceiveGameplaySettings(ClientData iclient, SerializedData sdata)
        {
            GameSettings settings = sdata.Get<GameSettings>();
            if (settings != null)
            {
                SetGameSettings(settings);
            }
        }

        public void ReceivePlayCard(ClientData iclient, SerializedData sdata)
        {
            MsgPlayCard msg = sdata.Get<MsgPlayCard>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerActionTurn(player) && !gameplay.IsResolving())
            {
                Card card = player.GetCard(msg.card_uid);
                if (card != null && card.player_id == player.player_id)
                    gameplay.PlayCard(card, msg.slot);
            }
        }

        public void ReceiveAttackTarget(ClientData iclient, SerializedData sdata)
        {
            MsgAttack msg = sdata.Get<MsgAttack>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerActionTurn(player) && !gameplay.IsResolving())
            {
                Card attacker = player.GetCard(msg.attacker_uid);
                Card target = game_data.GetCard(msg.target_uid);
                if (attacker != null && target != null && attacker.player_id == player.player_id)
                {
                    gameplay.AttackTarget(attacker, target);
                }
            }
        }

        public void ReceiveAttackPlayer(ClientData iclient, SerializedData sdata)
        {
            MsgAttackPlayer msg = sdata.Get<MsgAttackPlayer>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerActionTurn(player) && !gameplay.IsResolving())
            {
                Card attacker = player.GetCard(msg.attacker_uid);
                Player target = game_data.GetPlayer(msg.target_id);
                if (attacker != null && target != null && attacker.player_id == player.player_id)
                {
                    gameplay.AttackPlayer(attacker, target);
                }
            }
        }

        public void ReceiveMove(ClientData iclient, SerializedData sdata)
        {
            MsgPlayCard msg = sdata.Get<MsgPlayCard>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerActionTurn(player) && !gameplay.IsResolving())
            {
                Card card = player.GetCard(msg.card_uid);
                if (card != null && card.player_id == player.player_id)
                    gameplay.MoveCard(card, msg.slot);
            }
        }

        public void ReceiveCastCardAbility(ClientData iclient, SerializedData sdata)
        {
            MsgCastAbility msg = sdata.Get<MsgCastAbility>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerActionTurn(player) && !gameplay.IsResolving())
            {
                Card card = player.GetCard(msg.caster_uid);
                AbilityData iability = AbilityData.Get(msg.ability_id);
                if (card != null && card.player_id == player.player_id)
                    gameplay.CastAbility(card, iability);
            }
        }

        public void ReceiveSelectCard(ClientData iclient, SerializedData sdata)
        {
            MsgCard msg = sdata.Get<MsgCard>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerSelectorTurn(player) && !gameplay.IsResolving())
            {
                Card target = game_data.GetCard(msg.card_uid);
                gameplay.SelectCard(target);
            }
        }

        public void ReceiveSelectPlayer(ClientData iclient, SerializedData sdata)
        {
            MsgPlayer msg = sdata.Get<MsgPlayer>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerSelectorTurn(player) && !gameplay.IsResolving())
            {
                Player target = game_data.GetPlayer(msg.player_id);
                gameplay.SelectPlayer(target);
            }
        }

        public void ReceiveSelectSlot(ClientData iclient, SerializedData sdata)
        {
            Slot slot = sdata.Get<Slot>();
            Player player = GetPlayer(iclient);
            if (player != null && game_data.IsPlayerSelectorTurn(player) && !gameplay.IsResolving())
            {
                if(slot != null && slot.IsValid())
                    gameplay.SelectSlot(slot);
            }
        }

        public void ReceiveSelectChoice(ClientData iclient, SerializedData sdata)
        {
            MsgInt msg = sdata.Get<MsgInt>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerSelectorTurn(player) && !gameplay.IsResolving())
            {
                gameplay.SelectChoice(msg.value);
            }
        }

        public void ReceiveSelectCost(ClientData iclient, SerializedData sdata)
        {
            MsgInt msg = sdata.Get<MsgInt>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerSelectorTurn(player) && !gameplay.IsResolving())
            {
                gameplay.SelectCost(msg.value);
            }
        }

        public void ReceiveCancelSelection(ClientData iclient, SerializedData sdata)
        {
            Player player = GetPlayer(iclient);
            if (player != null && game_data.IsPlayerSelectorTurn(player) && !gameplay.IsResolving())
            {
                gameplay.CancelSelection();
            }
        }

        public void ReceiveSelectMulligan(ClientData iclient, SerializedData sdata)
        {
            MsgMulligan msg = sdata.Get<MsgMulligan>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null && game_data.IsPlayerMulliganTurn(player) && !gameplay.IsResolving())
            {
                gameplay.Mulligan(player, msg.cards);
            }
        }

        public void ReceiveEndTurn(ClientData iclient, SerializedData sdata)
        {
            Player player = GetPlayer(iclient);
            if (player != null && game_data.IsPlayerTurn(player))
            {
                gameplay.NextStep();
            }
        }

        public void ReceiveResign(ClientData iclient, SerializedData sdata)
        {
            Player player = GetPlayer(iclient);
            if (player != null && game_data.state != GameState.Connecting && game_data.state != GameState.GameEnded)
            {
                int winner = player.player_id == 0 ? 1 : 0;
                gameplay.EndGame(winner);
            }
        }

        public void ReceiveChat(ClientData iclient, SerializedData sdata)
        {
            MsgChat msg = sdata.Get<MsgChat>();
            Player player = GetPlayer(iclient);
            if (player != null && msg != null)
            {
                msg.player_id = player.player_id; //Force player id to sending client to avoid spoofing
                SendToAll(GameAction.ChatMessage, msg, NetworkDelivery.Reliable);
            }
        }

        //--- Setup Commands ------

        public virtual async void SetPlayerDeck(int player_id, string username, UserDeckData deck)
        {
            Player player = game_data.GetPlayer(player_id);
            if (player != null && game_data.state == GameState.Connecting)
            {
                UserData user = Authenticator.Get().UserData; //Offline game, get local user

                if(Authenticator.Get().IsApi())
                    user = await ApiClient.Get().LoadUserData(username); //Online game, validate from api

                //Use user API deck
                UserDeckData udeck = user?.GetDeck(deck.tid);
                if (user != null && udeck != null)
                {
                    if (user.IsDeckValid(udeck))
                    {
                        gameplay.SetPlayerDeck(player, udeck);
                        SendPlayerReady(player);
                        return;
                    }
                    else
                    {
                        Debug.Log(user.username + " deck is invalid: " + udeck.title);
                        return;
                    }
                }

                //Use premade deck
                DeckData cdeck = DeckData.Get(deck.tid);
                if (cdeck != null)
                    gameplay.SetPlayerDeck(player, cdeck);

                //Trust client in test mode
                else if (Authenticator.Get().IsTest())
                    gameplay.SetPlayerDeck(player, deck);

                //Deck not found
                else
                    Debug.Log("Player " + player_id + " deck not found: " + deck.tid);

                SendPlayerReady(player);
            }
        }

        public virtual void SetPlayerSettings(int player_id, PlayerSettings psettings)
        {
            if (game_data.state != GameState.Connecting)
                return; //Cant send setting if game already started

            Player player = game_data.GetPlayer(player_id);
            if (player != null && !player.ready)
            {
                player.avatar = psettings.avatar;
                player.cardback = psettings.cardback;
                player.is_ai = false;
                player.ready = true;
                SetPlayerDeck(player_id, player.username, psettings.deck);
                RefreshAll();
            }
        }

        public virtual void SetPlayerSettingsAI(int player_id, PlayerSettings psettings)
        {
            if (game_data.state != GameState.Connecting)
                return; //Cant send setting if game already started
            if (is_dedicated_server)
                return; //No AI allowed online server

            Player player = game_data.GetOpponentPlayer(player_id);
            if (player != null && !player.ready)
            {
                player.username = psettings.username;
                player.avatar = psettings.avatar;
                player.cardback = psettings.cardback;
                player.is_ai = true;
                player.ready = true;
                player.ai_level = psettings.ai_level;

                SetPlayerDeck(player.player_id, player.username, psettings.deck);
                RefreshAll();
            }
        }

        public virtual void SetGameSettings(GameSettings settings)
        {
            if (game_data.state == GameState.Connecting)
            {
                game_data.settings = settings;
                RefreshAll();
            }
        }

        //-------------

        public void AddClient(ClientData client)
        {
            if (!connected_clients.Contains(client))
                connected_clients.Add(client);
        }

        public void RemoveClient(ClientData client)
        {
            connected_clients.Remove(client);

            Player player = GetPlayer(client);
            if (player != null && player.connected)
            {
                player.connected = false;
                RefreshAll();
            }
        }

        public ClientData GetClient(ulong client_id)
        {
            foreach (ClientData client in connected_clients)
            {
                if (client.client_id == client_id)
                    return client;
            }
            return null;
        }

        public int AddPlayer(ClientData client)
        {
            if (!players.Contains(client))
                players.Add(client);

            int player_id = FindPlayerID(client.user_id);
            Player player = game_data.GetPlayer(player_id);
            if (player != null)
            {
                player.username = client.username;
                player.connected = true;
            }

            return player_id;
        }

        public int FindPlayerID(string user_id)
        {
            int index = 0;
            foreach (ClientData player in players)
            {
                if (player.user_id == user_id)
                    return index;
                index++;
            }
            return -1;
        }

        public Player GetPlayer(ClientData client)
        {
            return GetPlayer(client.user_id);
        }

        public Player GetPlayer(string user_id)
        {
            int player_id = FindPlayerID(user_id);
            return game_data?.GetPlayer(player_id);
        }

        public bool IsPlayer(string user_id)
        {
            Player player = GetPlayer(user_id);
            return player != null;
        }

        public bool IsConnectedPlayer(string user_id)
        {
            Player player = GetPlayer(user_id);
            return player != null && player.connected;
        }

        public int CountPlayers()
        {
            return players.Count;
        }

        public int CountConnectedClients()
        {
            int nb = 0;
            Game game = GetGameData();
            foreach (Player player in game.players)
            {
                if (player.IsConnected())
                {
                    nb++;
                }
            }
            return nb;
        }

        public Game GetGameData()
        {
            return gameplay.GetGameData();
        }

        public virtual bool HasGameStarted()
        {
            return gameplay.IsGameStarted();
        }

        public virtual bool HasGameEnded()
        {
            return gameplay.IsGameEnded();
        }

        public virtual bool IsGameExpired()
        {
            return expiration > game_expire_time; //Means that the game expired (everyone left or game ended)
        }

        public virtual bool IsWinExpired()
        {
            return win_expiration > win_expire_time; //Means that only one player is left, and he should win
        }

        protected virtual void OnGameStart()
        {
            SendToAll(GameAction.GameStart);

            if (is_dedicated_server && Authenticator.Get().IsApi())
            {
                //Create Match
                ApiClient.Get().CreateMatch(game_data);
            }
        }

        protected virtual void OnGameEnd(Player winner)
        {
            MsgPlayer msg = new MsgPlayer();
            msg.player_id = winner != null ? winner.player_id : -1;
            SendToAll(GameAction.GameEnd, msg, NetworkDelivery.Reliable);

            if (is_dedicated_server && Authenticator.Get().IsApi())
            {
                //End Match and give rewards
                ApiClient.Get().EndMatch(game_data, winner.player_id);
            }
        }

        protected virtual void OnTurnStart()
        {
            MsgPlayer msg = new MsgPlayer();
            msg.player_id = game_data.current_player;
            SendToAll(GameAction.NewTurn, msg, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardPlayed(Card card, Slot slot)
        {
            MsgPlayCard mdata = new MsgPlayCard();
            mdata.card_uid = card.uid;
            mdata.slot = slot;
            SendToAll(GameAction.CardPlayed, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardMoved(Card card, Slot slot)
        {
            MsgPlayCard mdata = new MsgPlayCard();
            mdata.card_uid = card.uid;
            mdata.slot = slot;
            SendToAll(GameAction.CardMoved, mdata, NetworkDelivery.Reliable);
        }
        
        protected virtual void OnCardSummoned(Card card, Slot slot)
        {
            MsgPlayCard mdata = new MsgPlayCard();
            mdata.card_uid = card.uid;
            mdata.slot = slot;
            SendToAll(GameAction.CardSummoned, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardTransformed(Card card)
        {
            MsgCard mdata = new MsgCard();
            mdata.card_uid = card.uid;
            SendToAll(GameAction.CardTransformed, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardDiscarded(Card card)
        {
            MsgCard mdata = new MsgCard();
            mdata.card_uid = card.uid;
            SendToAll(GameAction.CardDiscarded, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardDraw(int nb)
        {
            MsgInt mdata = new MsgInt();
            mdata.value = nb;
            SendToAll(GameAction.CardDrawn, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnValueRolled(int nb)
        {
            MsgInt mdata = new MsgInt();
            mdata.value = nb;
            SendToAll(GameAction.ValueRolled, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAttackStart(Card attacker, Card target)
        {
            MsgAttack mdata = new MsgAttack();
            mdata.attacker_uid = attacker.uid;
            mdata.target_uid = target.uid;
            mdata.damage = 0;
            SendToAll(GameAction.AttackStart, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAttackEnd(Card attacker, Card target)
        {
            MsgAttack mdata = new MsgAttack();
            mdata.attacker_uid = attacker.uid;
            mdata.target_uid = target.uid;
            mdata.damage = 0;
            SendToAll(GameAction.AttackEnd, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAttackPlayerStart(Card attacker, Player target)
        {
            MsgAttackPlayer mdata = new MsgAttackPlayer();
            mdata.attacker_uid = attacker.uid;
            mdata.target_id = target.player_id;
            mdata.damage = 0;
            SendToAll(GameAction.AttackPlayerStart, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAttackPlayerEnd(Card attacker, Player target)
        {
            MsgAttackPlayer mdata = new MsgAttackPlayer();
            mdata.attacker_uid = attacker.uid;
            mdata.target_id = target.player_id;
            mdata.damage = 0;
            SendToAll(GameAction.AttackPlayerEnd, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardDamaged(Card card, int damage)
        {
            MsgCardValue mdata = new MsgCardValue();
            mdata.card_uid = card.uid;
            mdata.value = damage;
            SendToAll(GameAction.CardDamaged, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnPlayerDamaged(Player player, int damage)
        {
            MsgPlayerValue mdata = new MsgPlayerValue();
            mdata.player_id = player.player_id;
            mdata.value = damage;
            SendToAll(GameAction.PlayerDamaged, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnCardHealed(Card card, int hp)
        {
            MsgCardValue mdata = new MsgCardValue();
            mdata.card_uid = card.uid;
            mdata.value = hp;
            SendToAll(GameAction.CardHealed, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnPlayerHealed(Player player, int hp)
        {
            MsgPlayerValue mdata = new MsgPlayerValue();
            mdata.player_id = player.player_id;
            mdata.value = hp;
            SendToAll(GameAction.PlayerHealed, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAbilityStart(AbilityData ability, Card caster)
        {
            MsgCastAbility mdata = new MsgCastAbility();
            mdata.ability_id = ability.id;
            mdata.caster_uid = caster.uid;
            mdata.target_uid = "";
            SendToAll(GameAction.AbilityTrigger, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAbilityTargetCard(AbilityData ability, Card caster, Card target)
        {
            MsgCastAbility mdata = new MsgCastAbility();
            mdata.ability_id = ability.id;
            mdata.caster_uid = caster.uid;
            mdata.target_uid = target != null ? target.uid : "";
            SendToAll(GameAction.AbilityTargetCard, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAbilityTargetPlayer(AbilityData ability, Card caster, Player target)
        {
            MsgCastAbilityPlayer mdata = new MsgCastAbilityPlayer();
            mdata.ability_id = ability.id;
            mdata.caster_uid = caster.uid;
            mdata.target_id = target != null ? target.player_id : -1;
            SendToAll(GameAction.AbilityTargetPlayer, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAbilityTargetSlot(AbilityData ability, Card caster, Slot target)
        {
            MsgCastAbilitySlot mdata = new MsgCastAbilitySlot();
            mdata.ability_id = ability.id;
            mdata.caster_uid = caster.uid;
            mdata.slot = target;
            SendToAll(GameAction.AbilityTargetSlot, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnAbilityEnd(AbilityData ability, Card caster)
        {
            MsgCastAbility mdata = new MsgCastAbility();
            mdata.ability_id = ability.id;
            mdata.caster_uid = caster.uid;
            mdata.target_uid = "";
            SendToAll(GameAction.AbilityEnd, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnSecretTriggered(Card secret, Card trigger)
        {
            MsgSecret mdata = new MsgSecret();
            mdata.secret_uid = secret.uid;
            mdata.triggerer_uid = trigger != null ? trigger.uid : "";
            SendToAll(GameAction.SecretTriggered, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void OnSecretResolved(Card secret, Card trigger)
        {
            MsgSecret mdata = new MsgSecret();
            mdata.secret_uid = secret.uid;
            mdata.triggerer_uid = trigger != null ? trigger.uid : "";
            SendToAll(GameAction.SecretResolved, mdata, NetworkDelivery.Reliable);
        }

        protected virtual void SendPlayerReady(Player player)
        {
            if (player != null && player.IsReady())
            {
                MsgInt mdata = new MsgInt();
                mdata.value = player.player_id;
                SendToAll(GameAction.PlayerReady, mdata, NetworkDelivery.Reliable);
            }
        }

        public virtual void RefreshAll()
        {
            MsgRefreshAll mdata = new MsgRefreshAll();
            mdata.game_data = GetGameData();
            SendToAll(GameAction.RefreshAll, mdata, NetworkDelivery.ReliableFragmentedSequenced);
        }

        public void SendToAll(ushort tag)
        {
            FastBufferWriter writer = new FastBufferWriter(128, Unity.Collections.Allocator.Temp, TcgNetwork.MsgSizeMax);
            writer.WriteValueSafe(tag);
            foreach (ClientData iclient in connected_clients)
            {
                if (iclient != null)
                {
                    Messaging.Send("refresh", iclient.client_id, writer, NetworkDelivery.Reliable);
                }
            }
            writer.Dispose();
        }

        public void SendToAll(ushort tag, INetworkSerializable data, NetworkDelivery delivery)
        {
            FastBufferWriter writer = new FastBufferWriter(128, Unity.Collections.Allocator.Temp, TcgNetwork.MsgSizeMax);
            writer.WriteValueSafe(tag);
            writer.WriteNetworkSerializable(data);
            foreach (ClientData iclient in connected_clients)
            {
                if (iclient != null)
                {
                    Messaging.Send("refresh", iclient.client_id, writer, delivery);
                }
            }
            writer.Dispose();
        }

        public ulong ServerID { get { return TcgNetwork.Get().ServerID; } }
        public NetworkMessaging Messaging { get { return TcgNetwork.Get().Messaging; } }
    }

    public struct QueuedGameAction
    {
        public ushort type;
        public ClientData client;
        public SerializedData sdata;
    }

}
