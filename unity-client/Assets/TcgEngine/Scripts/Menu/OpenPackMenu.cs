using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;

namespace TcgEngine.Client
{
    /// <summary>
    /// Main script for the open pack scene
    /// </summary>

    public class OpenPackMenu : MonoBehaviour
    {
        public GameObject card_prefab;

        private bool revealing = false;

        private static OpenPackMenu instance;

        void Awake()
        {
            instance = this;
        }

        void Update()
        {
            if (revealing && MouseInput.IsLeftClick())
            {
                bool all_revealed = true;
                foreach (PackCard card in PackCard.GetAll())
                {
                    if (!card.IsRevealed())
                        all_revealed = false;
                }

                if (all_revealed && PackCard.GetAll().Count > 0)
                    StopReveal();
            }
        }

        public void OpenPack(string pack_tid)
        {
            PackData pack = PackData.Get(pack_tid);
            if (pack != null)
            {
                OpenPack(pack);
            }
        }

        public void OpenPack(PackData pack)
        {
            if (Authenticator.Get().IsApi())
            {
                OpenPackApi(pack);
            }
            if (Authenticator.Get().IsTest())
            {
                OpenPackTest(pack);
            }
        }
        
        public async void OpenPackTest(PackData pack)
        {
            UserData udata = Authenticator.Get().UserData;
            if (!udata.HasPack(pack.id))
                return;

            List<UserCardData> cards = new List<UserCardData>();
            List <CardData> all_cards = CardData.GetAll(pack);

            if (pack.type == PackType.Random)
            {
                for (int i = 0; i < pack.cards; i++)
                {
                    RarityData rarity = GetRandomRarity(pack, i == 0);
                    VariantData variant = GetRandomVariant(pack);
                    List<CardData> vcards = GetCardArray(all_cards, rarity);
                    if (vcards.Count > 0)
                    {
                        CardData card = vcards[Random.Range(0, vcards.Count)];
                        UserCardData ucard = new UserCardData(card, variant);
                        cards.Add(ucard);
                    }
                }
            }

            if (pack.type == PackType.Fixed)
            {
                for (int i = 0; i < Mathf.Min(pack.cards, all_cards.Count); i++)
                {
                    CardData card = all_cards[i];
                    VariantData variant = VariantData.GetDefault();
                    UserCardData ucard = new UserCardData(card, variant);
                    cards.Add(ucard);
                }
            }

            //Reveal cards
            RevealCards(pack, cards.ToArray());

            //Save cards
            udata.AddPack(pack.id, -1);
            foreach (UserCardData card in cards)
            {
                udata.AddCard(card.tid, card.variant, card.quantity);
            }

            await Authenticator.Get().SaveUserData();
            HandPackArea.Get().LoadPacks();
        }

        public async void OpenPackApi(PackData pack)
        {
            UserData udata = Authenticator.Get().UserData;
            if (!udata.HasPack(pack.id))
                return;

            udata.AddPack(pack.id, -1);

            OpenPackRequest req = new OpenPackRequest();
            req.pack = pack.id;

            string url = ApiClient.ServerURL + "/users/packs/open";
            string json = ApiTool.ToJson(req);

            WebResponse res = await ApiClient.Get().SendPostRequest(url, json);
            if (res.success)
            {
                UserCardData[] cards = ApiTool.JsonToArray<UserCardData>(res.data);
                RevealCards(pack, cards);
            }

            HandPackArea.Get().LoadPacks();
        }

        public void RevealCards(PackData pack, UserCardData[] cards)
        {
            UserData udata = Authenticator.Get().UserData;
            CardbackData cb = CardbackData.Get(udata.cardback);
            HandPackArea.Get().Lock(true);
            revealing = true;

            int index = 0;
            foreach (UserCardData card in cards)
            {
                CardData icard = CardData.Get(card.tid);
                VariantData variant = VariantData.Get(card.variant);
                if (icard != null && variant != null)
                {
                    GameObject cobj = Instantiate(card_prefab, new Vector3(0f, -3f, 0f), Quaternion.identity);
                    PackCard pcard = cobj.GetComponent<PackCard>();
                    pcard.SetCard(pack, icard, variant);
                    BoardRef bref = BoardRef.Get(BoardRefType.PackCard, index);
                    Vector3 pos = bref != null ? bref.transform.position : Vector3.zero;
                    pcard.SetTarget(pos);
                    index++;
                }
            }
        }

        private List<CardData> GetCardArray(List<CardData>  all_cards, RarityData rarity)
        {
            List<CardData> cards = new List<CardData>();
            foreach (CardData acard in all_cards)
            {
                if (acard.rarity == rarity)
                    cards.Add(acard);
            }
            return cards;
        }

        private RarityData GetRandomRarity(PackData pack, bool is_first)
        {
            PackRarity[] rarities = is_first ? pack.rarities_1st : pack.rarities;
            if (rarities == null || rarities.Length == 0)
                return RarityData.GetFirst();

            int total = 0;
            foreach (PackRarity rarity in rarities)
            {
                total += rarity.probability;
            }

            int rvalue = Mathf.FloorToInt(Random.value * total);
            for (int i = 0; i < rarities.Length; i++)
            {
                PackRarity rarity = rarities[i];
                if (rvalue < rarity.probability)
                {
                    return rarity.rarity;
                }
                rvalue -= rarity.probability;
            }
            return RarityData.GetFirst();
        }

        private VariantData GetRandomVariant(PackData pack)
        {
            PackVariant[] variants = pack.variants;
            if (variants == null || variants.Length == 0)
                return VariantData.GetDefault();

            int total = 0;
            foreach (PackVariant variant in variants)
            {
                total += variant.probability;
            }

            int rvalue = Mathf.FloorToInt(Random.value * total);
            for (int i = 0; i < variants.Length; i++)
            {
                PackVariant variant = variants[i];
                if (rvalue < variant.probability)
                {
                    return variant.variant;
                }
                rvalue -= variant.probability;
            }
            return VariantData.GetDefault();
        }

        public void StopReveal()
        {
            revealing = false;
            HandPackArea.Get().Lock(false);
            foreach (PackCard card in PackCard.GetAll())
            {
                card.Remove();
            }
        }

        public void OnClickBack()
        {
            SceneNav.GoTo("Menu");
        }

        public static OpenPackMenu Get()
        {
            return instance;
        }
    }

}