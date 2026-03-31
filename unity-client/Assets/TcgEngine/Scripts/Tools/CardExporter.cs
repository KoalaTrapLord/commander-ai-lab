using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.UI;

namespace TcgEngine
{
    /// <summary>
    /// Use this export all your cards to png images (so they have the stats/ui on top of the card)
    /// </summary>

    public class CardExporter : MonoBehaviour
    {
        public string export_path = "C:/CardsExport";
        public int width = 856;
        public int height = 1200;
        public VariantData variant;

        [Header("References")]
        public Camera render_cam;
        public CardUI card_ui;

        private RenderTexture texture;
        private Texture2D export_texture;

        void Start()
        {
            if (variant == null)
                variant = VariantData.GetDefault();

            GenerateAll();
        }

        private async void GenerateAll()
        {
            QualitySettings.SetQualityLevel(QualitySettings.names.Length -1); //Set Max Quality level

            texture = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32);
            export_texture = new Texture2D(width, height, TextureFormat.ARGB32, false);
            texture.filterMode = FilterMode.Point;
            export_texture.filterMode = FilterMode.Point;
            render_cam.targetTexture = texture;
            render_cam.orthographicSize = height / 2;

            List<CardData> cards = CardData.GetAll();
            for (int i = 0; i < cards.Count; i++)
            {
                CardData card = cards[i];
                if (card.IsDeckbuilding())
                {
                    ShowText("Exporting: " + card.id);
                    GenerateCard(card);
                    await TimeTool.Delay(1);
                    ExportCard(card);
                    await TimeTool.Delay(2);
                }
            }

            ShowText("Completed!");
        }

        private void GenerateCard(CardData card)
        {
            card_ui.SetCard(card, variant);
            render_cam.Render();
        }

        private void ExportCard(CardData card)
        {
            RenderTexture.active = texture;
            export_texture.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            byte[] bytes = export_texture.EncodeToPNG();
            string file = card.id + ".png";
            File.WriteAllBytes(export_path + "/" + file, bytes);
            RenderTexture.active = null;
        }

        private void ShowText(string txt)
        {
            Debug.Log(txt);
        }
    }
}
