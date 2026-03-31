using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using UnityEngine.EventSystems;

namespace TcgEngine.UI
{

    public class HeroUI : MonoBehaviour
    {
        public bool opponent;
        public GameObject power_area;
        public Button power_button;
        public Image power_image;
        public GameObject power_mana_slot;
        public Text power_mana;

        public Material active_mat;
        public Material inactive_mat;

        private bool focus = false;

        private static List<HeroUI> ui_list = new List<HeroUI>();

        private void Awake()
        {
            ui_list.Add(this);
        }

        private void OnDestroy()
        {
            ui_list.Remove(this);
        }

        void Start()
        {
            power_area.SetActive(false);
            if (power_button != null)
                power_button.onClick.AddListener(OnClickPower);

            EventTrigger trigger = power_area.GetComponent<EventTrigger>();
            EventTrigger.Entry entry = new EventTrigger.Entry();
            entry.eventID = EventTriggerType.PointerEnter;
            entry.callback.AddListener((eventData) => { OnEnterMouse(); });
            EventTrigger.Entry exit = new EventTrigger.Entry();
            exit.eventID = EventTriggerType.PointerExit;
            exit.callback.AddListener((eventData) => { OnExitMouse(); });
            trigger.triggers.Add(entry);
            trigger.triggers.Add(exit);
        }

        private void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            Game gdata = GameClient.Get().GetGameData();
            Player player = GetPlayer();
            Card hero = player.hero;
            if (hero == null)
                return;

            AbilityData ability = hero.GetAbility(AbilityTrigger.Activate);
            if (ability != null)
            {
                power_image.sprite = hero.CardData.GetBoardArt(hero.VariantData);
                power_image.material = !hero.exhausted ? active_mat : inactive_mat;
                power_mana_slot?.SetActive(gdata.IsPlayerTurn(player) && !hero.exhausted);
                power_mana.text = ability.mana_cost.ToString();
            }

            if (power_button != null)
                power_button.interactable = ability != null && !hero.exhausted && gdata.IsPlayerTurn(player);

            if (hero != null && !power_area.activeSelf)
                power_area.SetActive(true);
        }

        public void OnClickPower()
        {
            Game gdata = GameClient.Get().GetGameData();
            Player player = GameClient.Get().GetPlayer();
            Card hero = player.hero;
            AbilityData ability = hero?.GetAbility(AbilityTrigger.Activate);
            if (ability != null && !opponent)
            {
                if (!hero.exhausted && !player.CanPayAbility(hero, ability))
                {
                    WarningText.ShowNoMana();
                    return;
                }
                
                if (!Tutorial.Get().CanDo(TutoEndTrigger.CastAbility, hero))
                    return;

                bool valid = gdata.IsPlayerActionTurn(player) && gdata.CanCastAbility(hero, ability);
                if (valid)
                {
                    GameClient.Get().CastAbility(hero, ability);
                }
            }
        }

        private void OnEnterMouse()
        {
            focus = true;
        }

        private void OnExitMouse()
        {
            focus = false;
        }

        private void OnDisable()
        {
            focus = false;
        }

        public bool IsFocus()
        {
            return focus;
        }

        public int GetPlayerID()
        {
            return opponent ? GameClient.Get().GetOpponentPlayerID() : GameClient.Get().GetPlayerID();
        }

        public Player GetPlayer()
        {
            Game gdata = GameClient.Get().GetGameData();
            return gdata.GetPlayer(GetPlayerID());
        }

        public Card GetCard()
        {
            Player player = GetPlayer();
            return player.hero;
        }

        public static HeroUI GetFocus()
        {
            foreach (HeroUI ui in ui_list)
            {
                if (ui.IsFocus())
                    return ui;
            }
            return null;
        }

        public static HeroUI Get(bool opponent)
        {
            foreach (HeroUI ui in ui_list)
            {
                if (ui.opponent == opponent)
                    return ui;
            }
            return null;
        }

        public static HeroUI Get(int player_id)
        {
            bool opponent = player_id != GameClient.Get().GetPlayerID();
            return Get(opponent);
        }
    }
}
