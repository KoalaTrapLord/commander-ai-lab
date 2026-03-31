using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace TcgEngine
{
    //Represent the current state of a player during the game (data only)

    [System.Serializable]
    public class Player
    {
        public int player_id;
        public string username;
        public string avatar;
        public string cardback;
        public string deck;

        public bool is_ai = false;
        public int ai_level;

        public bool connected = false; //Connected to server and game
        public bool ready = false;     //Sent all player data, ready to play

        public int hp;
        public int hp_max;
        public int mana = 0;
        public int mana_max = 0;
        public int kill_count = 0;

        public Dictionary<string, Card> cards_all = new Dictionary<string, Card>(); //Dictionnary for quick access to any card by UID
        public Card hero = null;

        public List<Card> cards_deck = new List<Card>();    //Cards in the player's deck
        public List<Card> cards_hand = new List<Card>();    //Cards in the player's hand
        public List<Card> cards_board = new List<Card>();   //Cards on the board
        public List<Card> cards_equip = new List<Card>();   //Cards equipped by characters
        public List<Card> cards_discard = new List<Card>(); //Cards in the player's discard
        public List<Card> cards_secret = new List<Card>();  //Cards in the player's secret area
        public List<Card> cards_temp = new List<Card>();    //Temporary cards that have just been created, not assigned to any zone yet

        public List<CardTrait> traits = new List<CardTrait>();              //Current persistant traits the cards has
        public List<CardTrait> ongoing_traits = new List<CardTrait>();      //Current ongoing traits the cards has

        public List<CardStatus> status = new List<CardStatus>();    //Current persistant (or with duration) traits the cards has
        public List<CardStatus> ongoing_status = new List<CardStatus>();    //Current ongoing traits the cards has

        public List<ActionHistory> history_list = new List<ActionHistory>();  //History of actions performed by the player

        public Player(int id) { this.player_id = id; }

        public bool IsReady() { return ready && cards_all.Count > 0; }
        public bool IsConnected() { return connected || is_ai; }

        public virtual void ClearOngoing() { ongoing_status.Clear(); ongoing_traits.Clear(); }

        //---- Cards ---------

        public void AddCard(List<Card> card_list, Card card)
        {
            card_list.Add(card);
        }

        public void RemoveCard(List<Card> card_list, Card card)
        {
            card_list.Remove(card);
        }

        public virtual void RemoveCardFromAllGroups(Card card)
        {
            cards_deck.Remove(card);
            cards_hand.Remove(card);
            cards_board.Remove(card);
            cards_equip.Remove(card);
            cards_discard.Remove(card);
            cards_secret.Remove(card);
            cards_temp.Remove(card);
            UnequipFromAllCards(card);
        }

        public virtual void UnequipFromAllCards(Card equip)
        {
            foreach (Card card in cards_board)
            {
                if (card.equipped_uid == equip.uid)
                    card.equipped_uid = null;
            }
        }

        public virtual Card GetRandomCard(List<Card> card_list, System.Random rand)
        {
            if (card_list.Count > 0)
                return card_list[rand.Next(0, card_list.Count)];
            return null;
        }

        public bool HasCard(List<Card> card_list, Card card)
        {
            return card_list.Contains(card);
        }

        public Card GetHandCard(string uid)
        {
            foreach (Card card in cards_hand)
            {
                if (card.uid == uid)
                    return card;
            }
            return null;
        }

        public Card GetBoardCard(string uid)
        {
            foreach (Card card in cards_board)
            {
                if (card.uid == uid)
                    return card;
            }
            return null;
        }

        public Card GetEquipCard(string uid)
        {
            foreach (Card card in cards_equip)
            {
                if (card.uid == uid)
                    return card;
            }
            return null;
        }

        public Card GetDeckCard(string uid)
        {
            foreach (Card card in cards_deck)
            {
                if (card.uid == uid)
                    return card;
            }
            return null;
        }

        public Card GetDiscardCard(string uid)
        {
            foreach (Card card in cards_discard)
            {
                if (card.uid == uid)
                    return card;
            }
            return null;
        }

        public Card GetBearerCard(Card equipment)
        {
            foreach (Card card in cards_board)
            {
                if (card != null && card.equipped_uid == equipment.uid)
                    return card;
            }
            return null;
        }

        public Card GetSlotCard(Slot slot)
        {
            foreach (Card card in cards_board)
            {
                if (card != null && card.slot == slot)
                    return card;
            }
            return null;
        }

        public Card GetCard(string uid)
        {
            if (uid != null)
            {
                bool valid = cards_all.TryGetValue(uid, out Card card);
                if (valid)
                    return card;
            }
            return null;
        }

        public bool IsOnBoard(Card card)
        {
            return card != null && GetBoardCard(card.uid) != null;
        }


        //---- Slots ---------

        public Slot GetRandomSlot(System.Random rand)
        {
            return Slot.GetRandom(player_id, rand);
        }

        public virtual Slot GetRandomEmptySlot(System.Random rand, List<Slot> list_mem = null)
        {
            List<Slot> valid = GetEmptySlots(list_mem);
            if (valid.Count > 0)
                return valid[rand.Next(0, valid.Count)];
            return Slot.None;
        }

        public virtual Slot GetRandomOccupiedSlot(System.Random rand, List<Slot> list_mem = null)
        {
            List<Slot> valid = GetOccupiedSlots(list_mem);
            if (valid.Count > 0)
                return valid[rand.Next(0, valid.Count)];
            return Slot.None;
        }

        public List<Slot> GetEmptySlots(List<Slot> list_mem = null)
        {
            List<Slot> valid = list_mem != null ? list_mem : new List<Slot>();
            foreach (Slot slot in Slot.GetAll(player_id))
            {
                Card slot_card = GetSlotCard(slot);
                if (slot_card == null)
                    valid.Add(slot);
            }
            return valid;
        }

        public List<Slot> GetOccupiedSlots(List<Slot> list_mem = null)
        {
            List<Slot> valid = list_mem != null ? list_mem : new List<Slot>();
            foreach (Slot slot in Slot.GetAll(player_id))
            {
                Card slot_card = GetSlotCard(slot);
                if (slot_card != null)
                    valid.Add(slot);
            }
            return valid;
        }

        //------ Custom Traits/Stats ---------

        public void SetTrait(string id, int value)
        {
            CardTrait trait = GetTrait(id);
            if (trait != null)
            {
                trait.value = value;
            }
            else
            {
                trait = new CardTrait(id, value);
                traits.Add(trait);
            }
        }

        public void AddTrait(string id, int value)
        {
            CardTrait trait = GetTrait(id);
            if (trait != null)
                trait.value += value;
            else
                SetTrait(id, value);
        }

        public void AddOngoingTrait(string id, int value)
        {
            CardTrait trait = GetOngoingTrait(id);
            if (trait != null)
            {
                trait.value += value;
            }
            else
            {
                trait = new CardTrait(id, value);
                ongoing_traits.Add(trait);
            }
        }

        public void RemoveTrait(string id)
        {
            for (int i = traits.Count - 1; i >= 0; i--)
            {
                if (traits[i].id == id)
                    traits.RemoveAt(i);
            }
        }

        public CardTrait GetTrait(string id)
        {
            foreach (CardTrait trait in traits)
            {
                if (trait.id == id)
                    return trait;
            }
            return null;
        }

        public CardTrait GetOngoingTrait(string id)
        {
            foreach (CardTrait trait in ongoing_traits)
            {
                if (trait.id == id)
                    return trait;
            }
            return null;
        }

        public List<CardTrait> GetAllTraits()
        {
            List<CardTrait> all_traits = new List<CardTrait>();
            all_traits.AddRange(traits);
            all_traits.AddRange(ongoing_traits);
            return all_traits;
        }

        public int GetTraitValue(TraitData trait)
        {
            if (trait != null)
                return GetTraitValue(trait.id);
            return 0;
        }

        public virtual int GetTraitValue(string id)
        {
            int val = 0;
            CardTrait stat1 = GetTrait(id);
            CardTrait stat2 = GetOngoingTrait(id);
            if (stat1 != null)
                val += stat1.value;
            if (stat2 != null)
                val += stat2.value;
            return val;
        }

        public bool HasTrait(TraitData trait)
        {
            if (trait != null)
                return HasTrait(trait.id);
            return false;
        }

        public bool HasTrait(string id)
        {
            foreach (CardTrait trait in traits)
            {
                if (trait.id == id)
                    return true;
            }
            return false;
        }

        //---- Status ---------

        public void AddStatus(StatusData status, int value, int duration)
        {
            if (status != null)
                AddStatus(status.effect, value, duration);
        }

        public void AddOngoingStatus(StatusData status, int value)
        {
            if (status != null)
                AddOngoingStatus(status.effect, value);
        }

        public void AddStatus(StatusType effect, int value, int duration)
        {
            if (effect != StatusType.None)
            {
                CardStatus status = GetStatus(effect);
                if (status == null)
                {
                    status = new CardStatus(effect, value, duration);
                    this.status.Add(status);
                }
                else
                {
                    status.value += value;
                    status.duration = Mathf.Max(status.duration, duration);
                    status.permanent = status.permanent || duration == 0;
                }
            }
        }

        public void AddOngoingStatus(StatusType effect, int value)
        {
            if (effect != StatusType.None)
            {
                CardStatus status = GetOngoingStatus(effect);
                if (status == null)
                {
                    status = new CardStatus(effect, value, 0);
                    ongoing_status.Add(status);
                }
                else
                {
                    status.value += value;
                }
            }
        }

        public void RemoveStatus(StatusType effect)
        {
            for (int i = status.Count - 1; i >= 0; i--)
            {
                if (status[i].type == effect)
                    status.RemoveAt(i);
            }
        }

        public CardStatus GetStatus(StatusType effect)
        {
            foreach (CardStatus status in status)
            {
                if (status.type == effect)
                    return status;
            }
            return null;
        }

        public CardStatus GetOngoingStatus(StatusType effect)
        {
            foreach (CardStatus status in ongoing_status)
            {
                if (status.type == effect)
                    return status;
            }
            return null;
        }

        public List<CardStatus> GetAllStatus()
        {
            List<CardStatus> all_status = new List<CardStatus>();
            all_status.AddRange(status);
            all_status.AddRange(ongoing_status);
            return all_status;
        }

        public bool HasStatus(StatusType effect)
        {
            return GetStatus(effect) != null || GetOngoingStatus(effect) != null;
        }

        public virtual int GetStatusValue(StatusType type)
        {
            CardStatus status1 = GetStatus(type);
            CardStatus status2 = GetOngoingStatus(type);
            int v1 = status1 != null ? status1.value : 0;
            int v2 = status2 != null ? status2.value : 0;
            return v1 + v2;
        }

        public virtual void ReduceStatusDurations()
        {
            for (int i = status.Count - 1; i >= 0; i--)
            {
                if (!status[i].permanent)
                {
                    status[i].duration -= 1;
                    if (status[i].duration <= 0)
                        status.RemoveAt(i);
                }
            }
        }

        //---- History ---------

        public void AddHistory(ushort type, Card card)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            history_list.Add(order);
        }

        public void AddHistory(ushort type, Card card, Card target)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            order.target_uid = target.uid;
            history_list.Add(order);
        }

        public void AddHistory(ushort type, Card card, Player target)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            order.target_id = target.player_id;
            history_list.Add(order);
        }

        public void AddHistory(ushort type, Card card, AbilityData ability)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            order.ability_id = ability.id;
            history_list.Add(order);
        }

        public void AddHistory(ushort type, Card card, AbilityData ability, Card target)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            order.ability_id = ability.id;
            order.target_uid = target.uid;
            history_list.Add(order);
        }

        public void AddHistory(ushort type, Card card, AbilityData ability, Player target)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            order.ability_id = ability.id;
            order.target_id = target.player_id;
            history_list.Add(order);
        }

        public void AddHistory(ushort type, Card card, AbilityData ability, Slot target)
        {
            ActionHistory order = new ActionHistory();
            order.type = type;
            order.card_id = card.card_id;
            order.card_uid = card.uid;
            order.ability_id = ability.id;
            order.slot = target;
            history_list.Add(order);
        }


        //---- Action Check ---------

        public virtual bool CanPayMana(Card card)
        {
            if (card.CardData.IsDynamicManaCost())
                return true;
            return mana >= card.GetMana();
        }

        public virtual void PayMana(Card card)
        {
            if (!card.CardData.IsDynamicManaCost())
                mana -= card.GetMana();
        }

        public virtual bool CanPayAbility(Card card, AbilityData ability)
        {
            bool exhaust = !card.exhausted || !ability.exhaust;
            return exhaust && mana >= ability.mana_cost;
        }

        public virtual bool IsDead()
        {
            if (cards_hand.Count == 0 && cards_board.Count == 0 && cards_deck.Count == 0)
                return true;
            if (hp <= 0)
                return true;
            return false;
        }

        //--------------------

        //Clone all player variables into another var, used mostly by the AI when building a prediction tree
        public static void Clone(Player source, Player dest)
        {
            dest.player_id = source.player_id;
            dest.is_ai = source.is_ai;
            dest.ai_level = source.ai_level;

            //Commented variables are not needed for ai predictions
            //dest.username = source.username;
            //dest.avatar = source.avatar;
            //dest.deck = source.deck;
            //dest.connected = source.connected;
            //dest.ready = source.ready;

            dest.hp = source.hp;
            dest.hp_max = source.hp_max;
            dest.mana = source.mana;
            dest.mana_max = source.mana_max;
            dest.kill_count = source.kill_count;

            Card.CloneNull(source.hero, ref dest.hero);
            Card.CloneDict(source.cards_all, dest.cards_all);
            Card.CloneListRef(dest.cards_all, source.cards_board, dest.cards_board);  
            Card.CloneListRef(dest.cards_all, source.cards_equip, dest.cards_equip);  
            Card.CloneListRef(dest.cards_all, source.cards_hand, dest.cards_hand);
            Card.CloneListRef(dest.cards_all, source.cards_deck, dest.cards_deck);
            Card.CloneListRef(dest.cards_all, source.cards_discard, dest.cards_discard);
            Card.CloneListRef(dest.cards_all, source.cards_secret, dest.cards_secret);
            Card.CloneListRef(dest.cards_all, source.cards_temp, dest.cards_temp);

            CardStatus.CloneList(source.status, dest.status);
            CardStatus.CloneList(source.ongoing_status, dest.ongoing_status);
        }
    }

    [System.Serializable]
    public class ActionHistory
    {
        public ushort type;
        public string card_id;
        public string card_uid;
        public string target_uid;
        public string ability_id;
        public int target_id;
        public Slot slot;
    }
}