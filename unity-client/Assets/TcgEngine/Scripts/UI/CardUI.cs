using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine;
using UnityEngine.Events;
using UnityEngine.EventSystems;
using TcgEngine.Client;

namespace TcgEngine.UI
{
    /// <summary>
    /// Scripts to display all stats of a card, 
    /// is used by other script that display cards like BoardCard, and HandCard, CollectionCard..
    /// </summary>

    public class CardUI : MonoBehaviour, IPointerClickHandler
    {
        public Image card_image;
        public Image frame_image;
        public Image team_icon;
        public Image rarity_icon;
        public Image attack_icon;
        public Image hp_icon;
        public Image cost_icon;
        public Text attack;
        public Text hp;
        public Text cost;

        public Text card_title;
        public Text card_text;

        public TraitUI[] stats;

        public UnityAction<CardUI> onClick;
        public UnityAction<CardUI> onClickRight;

        private CardData card;
        private VariantData variant;

        void Awake()
        {

        }

        public void SetCard(Card card)
        {
            if (card == null)
                return;

            SetCard(card.CardData, card.VariantData);

            if (cost != null)
                cost.text = card.GetMana().ToString();
            if (cost != null && card.CardData.IsDynamicManaCost())
                cost.text = "X";
            if (attack != null)
                attack.text = card.GetAttack().ToString();
            if (hp != null)
                hp.text = card.GetHP().ToString();

            foreach (TraitUI stat in stats)
                stat.SetCard(card);
        }

        public void SetCard(CardData card, VariantData variant)
        {
            if (card == null)
                return;

            this.card = card;
            this.variant = variant;

            if(card_image != null)
                card_image.sprite = card.GetFullArt(variant);
            if (frame_image != null)
                frame_image.sprite = variant.frame;
            if (card_title != null)
                card_title.text = card.GetTitle().ToUpper();
            if (card_text != null)
                card_text.text = card.GetText();

            if (attack_icon != null)
                attack_icon.enabled = card.IsCharacter();
            if (attack != null)
                attack.enabled = card.IsCharacter();
            if (hp_icon != null)
                hp_icon.enabled = card.IsBoardCard() || card.IsEquipment();
            if (hp != null)
                hp.enabled = card.IsBoardCard() || card.IsEquipment();
            if (cost_icon != null)
                cost_icon.enabled = card.type != CardType.Hero;
            if (cost != null)
                cost.enabled = card.type != CardType.Hero;

            if (cost != null)
                cost.text = card.mana.ToString();
            if (cost != null && card.IsDynamicManaCost())
                cost.text = "X";
            if (attack != null)
                attack.text = card.attack.ToString();
            if (hp != null)
                hp.text = card.hp.ToString();

            if (team_icon != null)
            {
                team_icon.sprite = card.team.icon;
                team_icon.enabled = team_icon.sprite != null;
            }

            if (rarity_icon != null)
            {
                rarity_icon.sprite = card.rarity.icon;
                rarity_icon.enabled = rarity_icon.sprite != null && card.type != CardType.Hero;
            }

            foreach (TraitUI stat in stats)
                stat.SetCard(card);

            if (!gameObject.activeSelf)
                gameObject.SetActive(true);
        }

        public void SetHP(int hp_value)
        {
            if (hp != null)
                hp.text = hp_value.ToString();
        }

        public void SetMaterial(Material mat)
        {
            if (card_image != null)
                card_image.material = mat;
            if (frame_image != null)
                frame_image.material = mat;
            if (team_icon != null)
                team_icon.material = mat;
            if (rarity_icon != null)
                rarity_icon.material = mat;
            if (attack_icon != null)
                attack_icon.material = mat;
            if (hp_icon != null)
                hp_icon.material = mat;
            if (cost_icon != null)
                cost_icon.material = mat;
        }

        public void SetOpacity(float opacity)
        {
            if (card_image != null)
                card_image.color = new Color(card_image.color.r, card_image.color.g, card_image.color.b, opacity);
            if (frame_image != null)
                frame_image.color = new Color(frame_image.color.r, frame_image.color.g, frame_image.color.b, opacity);
            if (team_icon != null)
                team_icon.color = new Color(team_icon.color.r, team_icon.color.g, team_icon.color.b, opacity);
            if (rarity_icon != null)
                rarity_icon.color = new Color(rarity_icon.color.r, rarity_icon.color.g, rarity_icon.color.b, opacity);
            if (attack_icon != null)
                attack_icon.color = new Color(attack_icon.color.r, attack_icon.color.g, attack_icon.color.b, opacity);
            if (hp_icon != null)
                hp_icon.color = new Color(hp_icon.color.r, hp_icon.color.g, hp_icon.color.b, opacity);
            if (cost_icon != null)
                cost_icon.color = new Color(cost_icon.color.r, cost_icon.color.g, cost_icon.color.b, opacity);
            if (attack != null)
                attack.color = new Color(attack.color.r, attack.color.g, attack.color.b, opacity);
            if (hp != null)
                hp.color = new Color(hp.color.r, hp.color.g, hp.color.b, opacity);
            if (cost != null)
                cost.color = new Color(cost.color.r, cost.color.g, cost.color.b, opacity);
            if (card_title != null)
                card_title.color = new Color(card_title.color.r, card_title.color.g, card_title.color.b, opacity);
            if (card_text != null)
                card_text.color = new Color(card_text.color.r, card_text.color.g, card_text.color.b, opacity);
        }

        public void Hide()
        {
            if (gameObject.activeSelf)
                gameObject.SetActive(false);
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            if (eventData.button == PointerEventData.InputButton.Left)
            {
                if (onClick != null)
                    onClick.Invoke(this);
            }

            if (eventData.button == PointerEventData.InputButton.Right)
            {
                if (onClickRight != null)
                    onClickRight.Invoke(this);
            }
        }

        public CardData GetCard()
        {
            return card;
        }

        public VariantData GetVariant()
        {
            return variant;
        }
    }
}
