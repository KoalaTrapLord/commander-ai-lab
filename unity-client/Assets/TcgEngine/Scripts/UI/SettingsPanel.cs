using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace TcgEngine.UI
{
    public class SettingsPanel : UIPanel
    {
        public string tab_group;
        public SliderDrag master_vol;
        public SliderDrag music_vol;
        public SliderDrag sfx_vol;
        public SliderDrag quality;
        public SliderDrag resolution;
        public Toggle windowed;

        public Text master_vol_txt;
        public Text music_vol_txt;
        public Text sfx_vol_txt;
        public Text quality_txt;
        public Text resolution_txt;

        public static HashSet<string> reso_hash = new HashSet<string>();
        public static List<Resolution> resolutions = new List<Resolution>();
        private bool refreshing = false;

        private static SettingsPanel instance;

        protected override void Awake()
        {
            base.Awake();
            instance = this;
        }

        protected override void Start()
        {
            base.Start();

            //Default min max
            master_vol.minValue = 0;
            master_vol.maxValue = 100;
            music_vol.minValue = 0;
            music_vol.maxValue = 100;
            sfx_vol.minValue = 0;
            sfx_vol.maxValue = 100;
            quality.minValue = 0;
            resolution.minValue = 0;

            master_vol.onValueChanged += RefreshText;
            music_vol.onValueChanged += RefreshText;
            sfx_vol.onValueChanged += RefreshText;
            quality.onValueChanged += RefreshText;
            resolution.onValueChanged += RefreshText;

            master_vol.onEndDrag += OnChangeAudio;
            music_vol.onEndDrag += OnChangeAudio;
            sfx_vol.onEndDrag += OnChangeAudio;
            quality.onEndDrag += OnChangeQuality;
            resolution.onEndDrag += OnChangeResolution;
            windowed.onValueChanged.AddListener(OnChangeWindowed);

            foreach (Resolution reso in Screen.resolutions)
            {
                string reso_tag = reso.width + "x" + reso.height;
                if (!reso_hash.Contains(reso_tag))
                {
                    resolutions.Add(reso);
                    reso_hash.Add(reso_tag);
                }
            }

            quality.maxValue = QualitySettings.names.Length - 1;
            resolution.maxValue = resolutions.Count - 1;

            foreach (TabButton btn in TabButton.GetAll(tab_group))
                btn.onClick += OnClickTab;
        }

        private void RefreshPanel()
        {
            refreshing = true;
            master_vol.value = AudioTool.Get().master_vol * 100f;
            music_vol.value = AudioTool.Get().music_vol * 100f;
            sfx_vol.value = AudioTool.Get().sfx_vol * 100f;

            int quality_value = QualitySettings.GetQualityLevel();
            int reso_value = GetResolutionIndex();
            bool windowed_value = !Screen.fullScreen;

            quality.value = quality_value;
            resolution.value = reso_value;
            windowed.isOn = windowed_value;
            refreshing = false;

            RefreshText();
        }

        private void RefreshText()
        {
            master_vol_txt.text = master_vol.value.ToString();
            music_vol_txt.text = music_vol.value.ToString();
            sfx_vol_txt.text = sfx_vol.value.ToString();

            int quality_value = Mathf.RoundToInt(quality.value);
            quality_txt.text = QualitySettings.names[quality_value];
            resolution_txt.text = "";

            int reso_value = Mathf.RoundToInt(resolution.value);
            if (resolutions.Count > 0)
            {
                Resolution resolu = resolutions[reso_value];
                string reso_tag = resolu.width + "x" + resolu.height + " " + Screen.currentResolution.refreshRate + "Hz";
                resolution_txt.text = reso_tag;
            }
        }

        private void OnChangeAudio()
        {
            if (!refreshing)
            {
                AudioTool.Get().master_vol = master_vol.value / 100f;
                AudioTool.Get().sfx_vol = sfx_vol.value / 100f;
                AudioTool.Get().music_vol = music_vol.value / 100f;
                AudioTool.Get().RefreshVolume();
                AudioTool.Get().SavePrefs();
                RefreshText();
            }
        }

        private void OnChangeQuality()
        {
            if (!refreshing)
            {
                int quality_value = Mathf.RoundToInt(quality.value);
                QualitySettings.SetQualityLevel(quality_value);
                RefreshText();
            }
        }

        private void OnChangeResolution()
        {
            if (!refreshing && resolutions.Count > 0)
            {
                int reso_value = Mathf.RoundToInt(resolution.value);
                Resolution resolu = resolutions[reso_value];
                Screen.SetResolution(resolu.width, resolu.height, !windowed.isOn);
                RefreshText();
            }
        }

        private void OnChangeWindowed(bool val)
        {
            OnChangeResolution();
        }

        private void OnClickTab()
        {
            Hide();
        }

        public void OnClickOK()
        {
            Hide();
        }
        
        private int GetResolutionIndex()
        {
            int dist_min = 99999;
            int closest = 0;
            for (int i=0; i<resolutions.Count; i++)
            {
                Resolution res = resolutions[i];
                int dist = Mathf.Abs(res.height - Screen.height) + Mathf.Abs(res.width - Screen.width);
                if (dist < dist_min)
                {
                    dist_min = dist;
                    closest = i;
                }
            }
            return closest;
        }

        public override void Show(bool instant = false)
        {
            base.Show(instant);
            RefreshPanel();
        }

        public override void Hide(bool instant = false)
        {
            base.Hide(instant);
        }

        public static SettingsPanel Get()
        {
            return instance;
        }
    }
}