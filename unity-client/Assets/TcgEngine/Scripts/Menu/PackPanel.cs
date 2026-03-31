using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// Pack panel is similar to the collection, but shows all the packs you own and all available packs
    /// </summary>

    public class PackPanel : UIPanel
    {
        [Header("Packs")]
        public ScrollRect scroll_rect;
        public RectTransform scroll_content;
        public CardGrid grid_content;
        public GameObject pack_prefab;

        private List<GameObject> pack_list = new List<GameObject>();

        private static PackPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;

            //Delete grid content
            for (int i = 0; i < grid_content.transform.childCount; i++)
                Destroy(grid_content.transform.GetChild(i).gameObject);

        }

        protected override void Start()
        {
            base.Start();

        }

        protected override void Update()
        {
            base.Update();

        }

        public async void ReloadUserPack()
        {
            await Authenticator.Get().LoadUserData();
            RefreshPacks();
        }

        private void RefreshAll()
        {
            RefreshPacks();
            RefreshStarterDeck();
        }

        public void RefreshPacks()
        {
            UserData udata = Authenticator.Get().UserData;

            foreach (GameObject card in pack_list)
                Destroy(card.gameObject);
            pack_list.Clear();

            foreach (PackData pack in PackData.GetAllAvailable())
            {
                GameObject nPack = Instantiate(pack_prefab, grid_content.transform);
                PackUI pack_ui = nPack.GetComponentInChildren<PackUI>();
                pack_ui.SetPack(pack, udata.GetPackQuantity(pack.id));
                pack_ui.onClick += OnClickPack;
                pack_ui.onClickRight += OnClickPack;
                pack_list.Add(nPack);
            }
        }

        private void RefreshStarterDeck()
        {
            UserData udata = Authenticator.Get().UserData;
            if (udata != null && (udata.cards.Length == 0 || udata.rewards.Length == 0))
            {
                if (GameplayData.Get().starter_decks.Length > 0)
                {
                    StarterDeckPanel.Get().Show();
                }
            }
        }
        
        public void OnClickPack(PackUI pack)
        {
            PackZoomPanel.Get().ShowPack(pack.GetPack());
        }

        public void OnClickCardRight(PackUI pack)
        {
            PackZoomPanel.Get().ShowPack(pack.GetPack());
        }

        public void OnClickOpenPacks()
        {
            MainMenu.Get().FadeToScene("OpenPack");
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshAll();
        }

        public static PackPanel Get()
        {
            return instance;
        }
    }
}