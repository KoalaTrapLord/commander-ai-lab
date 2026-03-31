using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    /// <summary>
    /// When you click on a pack in the PackPanel, a box will appear to show more information about it
    /// You can also buy pack in this panel
    /// </summary>

    public class PackZoomPanel : UIPanel
    {
        public PackUI pack_ui;
        public Text desc;

        public GameObject buy_area;
        public InputField buy_quantity;
        public Text buy_cost;
        public Text buy_error;

        private PackData pack;

        private static PackZoomPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;

            TabButton.onClickAny += OnClickTab;
        }

        private void OnDestroy()
        {
            TabButton.onClickAny -= OnClickTab;
        }

        protected override void Update()
        {
            base.Update();

            if (pack != null)
            {
                int quantity = GetBuyQuantity();
                buy_cost.text = (pack.cost * quantity).ToString();
            }
        }

        public void ShowPack(PackData pack)
        {
            this.pack = pack;

            UserData udata = Authenticator.Get().UserData;
            int quantity = udata.GetPackQuantity(pack.id);
            pack_ui.SetPack(pack, quantity);
            desc.text = pack.GetDesc();
            buy_quantity.text = "1";
            buy_error.text = "";
            buy_area?.SetActive(pack.available);

            Show();
        }

        private async void BuyPackTest()
        {
            int quantity = GetBuyQuantity();
            int cost = (quantity * pack.cost);
            if (quantity <= 0)
                return;

            UserData udata = Authenticator.Get().UserData;
            if (udata.coins < cost)
                return;

            udata.AddPack(pack.id, quantity);
            udata.coins -= cost;
            await Authenticator.Get().SaveUserData();
            PackPanel.Get().ReloadUserPack();
            Hide();
        }

        private async void BuyPackApi()
        {
            BuyPackRequest req = new BuyPackRequest();
            req.pack = pack.id;
            req.quantity = GetBuyQuantity();

            if (req.quantity <= 0)
                return;

            string url = ApiClient.ServerURL + "/users/packs/buy/";
            string jdata = ApiTool.ToJson(req);
            buy_error.text = "";

            WebResponse res = await ApiClient.Get().SendPostRequest(url, jdata);
            if (res.success)
            {
                PackPanel.Get().ReloadUserPack();
                Hide();
            }
            else
            {
                buy_error.text = res.error;
            }
        }

        public void OnClickBuy()
        {
            if (Authenticator.Get().IsTest())
            {
                BuyPackTest();
            }
            if (Authenticator.Get().IsApi())
            {
                BuyPackApi();
            }
        }

        private void OnClickTab(TabButton btn)
        {
            if (btn.group == "menu")
                Hide();
        }

        public int GetBuyQuantity()
        {
            bool success = int.TryParse(buy_quantity.text, out int quantity);
            if (success)
                return quantity;
            return 0;
        }

        public PackData GetPack()
        {
            return pack;
        }

        public static PackZoomPanel Get()
        {
            return instance;
        }
    }
}