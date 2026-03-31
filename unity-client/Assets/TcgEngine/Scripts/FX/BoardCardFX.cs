using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.Client;
using UnityEngine.Events;
using TcgEngine;

namespace TcgEngine.FX
{
    /// <summary>
    /// All FX/anims related to a card on the board
    /// </summary>

    public class BoardCardFX : MonoBehaviour
    {
        public Material kill_mat;
        public string kill_mat_fade = "noise_fade";

        private BoardCard bcard;

        private ParticleSystem exhausted_fx = null;

        private Dictionary<StatusType, GameObject> status_fx_list = new Dictionary<StatusType, GameObject>();

        void Awake()
        {
            bcard = GetComponent<BoardCard>();
            bcard.onKill += OnKill;
        }

        void Start()
        {
            GameClient client = GameClient.Get();
            client.onCardMoved += OnMove;
            client.onCardPlayed += OnPlayed;
            client.onCardDamaged += OnCardDamaged;
            client.onAttackStart += OnAttack;
            client.onAttackPlayerStart += OnAttackPlayer;
            client.onAbilityStart += OnAbilityStart;
            client.onAbilityTargetCard += OnAbilityEffect;
            client.onAbilityEnd += OnAbilityAfter;

            OnSpawn();
        }

        private void OnDestroy()
        {
            GameClient client = GameClient.Get();
            client.onCardMoved -= OnMove;
            client.onCardPlayed -= OnPlayed;
            client.onCardDamaged -= OnCardDamaged;
            client.onAttackStart -= OnAttack;
            client.onAttackPlayerStart -= OnAttackPlayer;
            client.onAbilityStart -= OnAbilityStart;
            client.onAbilityTargetCard -= OnAbilityEffect;
            client.onAbilityEnd -= OnAbilityAfter;
        }
        
        void Update()
        {
            if (!GameClient.Get().IsReady())
                return;

            Card card = bcard.GetCard();

            //Status FX
            List<CardStatus> status_all = card.GetAllStatus();
            foreach (CardStatus status in status_all)
            {
                StatusData istatus = StatusData.Get(status.type);
                if (istatus != null && !status_fx_list.ContainsKey(status.type) && istatus.status_fx != null)
                {
                    GameObject fx = Instantiate(istatus.status_fx, transform);
                    fx.transform.localPosition = Vector3.zero;
                    status_fx_list[istatus.effect] = fx;
                }
            }

            //Remove status FX
            List<StatusType> remove_list = new List<StatusType>();
            foreach (KeyValuePair<StatusType, GameObject> pair in status_fx_list)
            {
                if (!card.HasStatus(pair.Key))
                {
                    remove_list.Add(pair.Key);
                    Destroy(pair.Value);
                }
            }

            foreach (StatusType status in remove_list)
                status_fx_list.Remove(status);

            //Exhausted add/remove
            if (exhausted_fx != null && !exhausted_fx.isPlaying && card.exhausted)
                exhausted_fx.Play();
            if (exhausted_fx != null && exhausted_fx.isPlaying && !card.exhausted)
                exhausted_fx.Stop();
        }

        private void OnSpawn()
        {
            CardData icard = bcard.GetCardData();

            //Spawn Audio
            AudioClip audio = icard?.spawn_audio != null ? icard.spawn_audio : AssetData.Get().card_spawn_audio;
            AudioTool.Get().PlaySFX("card_spawn", audio);

            //Spawn FX
            GameObject spawn_fx = icard.spawn_fx != null ? icard.spawn_fx : AssetData.Get().card_spawn_fx;
            FXTool.DoFX(spawn_fx, transform.position);

            //Spawn dissolve fx
            if (GameTool.IsURP())
            {
                SpriteRenderer render = bcard.card_sprite;
                render.material = kill_mat;

                FadeSetVal(bcard.card_sprite, 0f);
                FadeKill(bcard.card_sprite, 1f, 0.5f);
            }

            //Exhausted fx
            if (AssetData.Get().card_exhausted_fx != null)
            {
                GameObject efx = Instantiate(AssetData.Get().card_exhausted_fx, transform);
                efx.transform.localPosition = Vector3.zero;
                exhausted_fx = efx.GetComponent<ParticleSystem>();
            }

            //Idle status
            TimeTool.WaitFor(1f, () =>
            {
                if (icard.idle_fx != null)
                {
                    GameObject fx = Instantiate(icard.idle_fx, transform);
                    fx.transform.localPosition = Vector3.zero;
                }
            });
        }

        private void OnKill()
        {
            StartCoroutine(KillRoutine());
        }

        private IEnumerator KillRoutine()
        {
            yield return new WaitForSeconds(0.5f);

            CardData icard = bcard.GetCardData();

            //Death FX
            GameObject death_fx = icard.death_fx != null ? icard.death_fx : AssetData.Get().card_destroy_fx;
            FXTool.DoFX(death_fx, transform.position);

            //Death audio
            AudioClip audio = icard?.death_audio != null ? icard.death_audio : AssetData.Get().card_destroy_audio;
            AudioTool.Get().PlaySFX("card_spawn", audio);

            //Death dissolve fx
            if (GameTool.IsURP())
            {
                FadeKill(bcard.card_sprite, 0f, 0.5f);
            }
        }
		
		private void FadeSetVal(SpriteRenderer render, float val)
        {
            render.material = kill_mat;
            render.material.SetFloat(kill_mat_fade, val);
        }

        private void FadeKill(SpriteRenderer render, float val, float duration)
        {
            AnimMatFX anim = AnimMatFX.Create(render.gameObject, render.material);
            anim.SetFloat(kill_mat_fade, val, duration);
        }

        private void OnMove(Card card, Slot slot)
        {
            AudioTool.Get().PlaySFX("card_move", AssetData.Get().card_move_audio);
        }

        private void OnPlayed(Card card, Slot slot)
        {
            //Playing equipment
            Card ecard = bcard?.GetEquipCard();
            if (ecard != null && card.uid == ecard.uid && transform != null)
            {
                FXTool.DoFX(ecard.CardData.spawn_fx, transform.position);
                AudioTool.Get().PlaySFX("card_spawn", ecard.CardData.spawn_audio);
            }
        }

        private void OnCardDamaged(Card target, int damage)
        {
            Card card = bcard.GetCard();
            if (card.uid == target.uid && damage > 0)
            {
                DamageFX(bcard.transform, damage);
            }
        }

        private void OnAttack(Card attacker, Card target)
        {
            Card card = bcard.GetCard();
            CardData icard = bcard.GetCardData();
            if (attacker == null || target == null)
                return;

            if (card.uid == attacker.uid)
            {
                BoardCard btarget = BoardCard.Get(target.uid);
                if (btarget != null)
                {
                    //Card charge into target
                    ChargeInto(btarget);

                    //Attack FX and Audio
                    GameObject fx = icard.attack_fx != null ? icard.attack_fx : AssetData.Get().card_attack_fx;
                    FXTool.DoSnapFX(fx, transform);
                    AudioClip audio = icard?.attack_audio != null ? icard.attack_audio : AssetData.Get().card_attack_audio;
                    AudioTool.Get().PlaySFX("card_attack", audio);

                    //Equip FX
                    Card ecard = bcard.GetEquipCard();
                    if (ecard != null)
                    {
                        FXTool.DoFX(ecard.CardData.attack_fx, transform.position);
                        AudioTool.Get().PlaySFX("card_attack_equip", ecard.CardData.attack_audio);
                    }
                }
            }

        }

        private void OnAttackPlayer(Card attacker, Player player)
        {
            if (attacker == null || player == null)
                return;

            Card card = bcard.GetCard();
            if (card.uid == attacker.uid)
            {
                bool is_other = player.player_id != GameClient.Get().GetPlayerID();
                CardData icard = bcard.GetCardData();
                BoardSlotPlayer zone = BoardSlotPlayer.Get(is_other);

                ChargeIntoPlayer(zone);

                AudioClip audio = icard?.attack_audio != null ? icard.attack_audio : AssetData.Get().card_attack_audio;
                AudioTool.Get().PlaySFX("card_attack", audio);

                //Equip FX
                Card ecard = bcard.GetEquipCard();
                if (ecard != null)
                {
                    FXTool.DoFX(ecard.CardData.attack_fx, transform.position);
                    AudioTool.Get().PlaySFX("card_attack_equip", ecard.CardData.attack_audio);
                }
            }
        }

        private void DamageFX(Transform target, int value, float delay = 0.5f)
        {
            TimeTool.WaitFor(delay, () =>
            {
                GameObject fx = FXTool.DoFX(AssetData.Get().damage_fx, target.position);
                fx.GetComponent<DamageFX>().SetValue(value);
            });
        }

        private void ChargeInto(BoardCard target)
        {
            if (target != null)
            {
                ChargeInto(target.gameObject);

                CardData icard = target.GetCardData();
                TimeTool.WaitFor(0.25f, () =>
                {
                    //Damage fx and audio
                    GameObject prefab = icard.damage_fx ? icard.damage_fx : AssetData.Get().card_damage_fx;
                    AudioClip audio = icard.damage_audio ? icard.damage_audio : AssetData.Get().card_damage_audio;
                    FXTool.DoFX(prefab, target.transform.position);
                    AudioTool.Get().PlaySFX("card_hit", audio);
                });
            }
        }

        private void ChargeIntoPlayer(BoardSlotPlayer target)
        {
            if (target != null)
            {
                ChargeInto(target.gameObject);

                TimeTool.WaitFor(0.25f, () =>
                {
                    //Damage fx and audio
                    FXTool.DoFX(AssetData.Get().player_damage_fx, target.transform.position);
                    AudioClip audio = AssetData.Get().player_damage_audio;
                    AudioTool.Get().PlaySFX("card_hit", audio);
                });
            }
        }

        private void ChargeInto(GameObject target)
        {
            if (target != null)
            {
                int current_order = bcard.card_sprite.sortingOrder;
                Vector3 dir = target.transform.position - transform.position;
                Vector3 target_pos = target.transform.position - dir.normalized * 1f;
                Vector3 current_pos = transform.position;
                bcard.SetOrder(current_order + 10);

                AnimFX anim = AnimFX.Create(gameObject);
                anim.MoveTo(current_pos - dir.normalized * 0.5f, 0.3f);
                anim.MoveTo(target.transform.position, 0.1f);
                anim.MoveTo(current_pos, 0.3f);
                anim.Callback(0f, () =>
                {
                    if (bcard != null)
                        bcard.SetOrder(current_order);
                });
            }
        }

        private void OnAbilityStart(AbilityData iability, Card caster)
        {
            if (iability != null && caster != null)
            {
                if (caster.uid == bcard.GetCardUID())
                {
                    FXTool.DoSnapFX(iability.caster_fx, bcard.transform);
                    AudioTool.Get().PlaySFX("ability", iability.cast_audio);
                }
            }
        }

        private void OnAbilityAfter(AbilityData iability, Card caster)
        {
            if (iability != null && caster != null)
            {
                if (caster.uid == bcard.GetCardUID())
                {

                }
            }
        }

        private void OnAbilityEffect(AbilityData iability, Card caster, Card target)
        {
            if (iability != null && caster != null && target != null)
            {
                if (target.uid == bcard.GetCardUID())
                {
                    FXTool.DoSnapFX(iability.target_fx, bcard.transform);
                    FXTool.DoProjectileFX(iability.projectile_fx, GetFXSource(caster), bcard.transform, iability.GetDamage());
                    AudioTool.Get().PlaySFX("ability_effect", iability.target_audio);
                }

                if (caster.uid == bcard.GetCardUID())
                {
                    if (iability.charge_target && caster.CardData.IsBoardCard())
                    {
                        BoardCard btarget = BoardCard.Get(target.uid);
                        ChargeInto(btarget);
                    }
                }
            }
        }

        private Transform GetFXSource(Card caster)
        {
            if (caster.CardData.IsBoardCard())
            {
                BoardCard bcard = BoardCard.Get(caster.uid);
                if (bcard != null)
                    return bcard.transform;
            }
            else
            {
                BoardSlotPlayer slot = BoardSlotPlayer.Get(caster.player_id);
                if (slot != null)
                    return slot.transform;
            }
            return null;
        }
    }
}
