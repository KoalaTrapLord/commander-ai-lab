using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using TMPro;
using Newtonsoft.Json;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Training scene — ML model training dashboard.
    /// Stats panel, start/stop training, live accuracy+loss charts,
    /// model version history, export model, training log, feature importance.
    /// </summary>
    public class TrainingController : MonoBehaviour
    {
        [Header("Navigation")]
        [SerializeField] private Button backButton;

        [Header("Stats Panel")]
        [SerializeField] private TMP_Text cardCountText;
        [SerializeField] private TMP_Text sessionCountText;
        [SerializeField] private TMP_Text modelVersionText;
        [SerializeField] private TMP_Text lastTrainedText;

        [Header("Controls")]
        [SerializeField] private Button startTrainingButton;
        [SerializeField] private Button stopTrainingButton;
        [SerializeField] private Button exportModelButton;
        [SerializeField] private TMP_Text statusText;

        [Header("Live Charts")]
        [SerializeField] private RectTransform accuracyChartRect;
        [SerializeField] private RectTransform lossChartRect;
        [SerializeField] private TMP_Text accuracyLabel;
        [SerializeField] private TMP_Text lossLabel;

        [Header("Feature Importance Chart")]
        [SerializeField] private Transform featureBarParent;
        [SerializeField] private GameObject featureBarPrefab;

        [Header("Model History")]
        [SerializeField] private Transform historyParent;
        [SerializeField] private GameObject historyRowPrefab;

        [Header("Training Log")]
        [SerializeField] private TMP_Text logText;
        [SerializeField] private ScrollRect logScrollRect;

        [Header("Error")]
        [SerializeField] private GameObject errorPanel;
        [SerializeField] private TMP_Text errorText;

        private bool _isTraining = false;
        private Coroutine _pollCoroutine;
        private readonly List<float> _accuracyHistory = new();
        private readonly List<float> _lossHistory = new();
        private const float PollInterval = 2f;

        private void Start()
        {
            backButton.onClick.AddListener(OnBack);
            startTrainingButton.onClick.AddListener(OnStartTraining);
            stopTrainingButton.onClick.AddListener(OnStopTraining);
            exportModelButton.onClick.AddListener(OnExportModel);

            stopTrainingButton.interactable = false;
            errorPanel.SetActive(false);

            LoadStats();
            LoadModelHistory();
        }

        private void OnDestroy()
        {
            if (_pollCoroutine != null) StopCoroutine(_pollCoroutine);
        }

        // ── Stats ─────────────────────────────────────────────────────────
        private void LoadStats()
        {
            ApiClient.Instance.GetRaw("/api/ml/stats",
                json =>
                {
                    try
                    {
                        var s = JsonConvert.DeserializeObject<MlStats>(json);
                        cardCountText.text    = $"Cards: {s.card_count:N0}";
                        sessionCountText.text = $"Sessions: {s.session_count:N0}";
                        modelVersionText.text = $"Model v{s.model_version}";
                        lastTrainedText.text  = $"Last trained: {s.last_trained ?? "never"}";
                    }
                    catch (Exception e) { ShowError($"Stats parse error: {e.Message}"); }
                },
                err => ShowError($"Stats load failed: {err}"));
        }

        // ── Model History ─────────────────────────────────────────────────
        private void LoadModelHistory()
        {
            foreach (Transform t in historyParent) Destroy(t.gameObject);

            ApiClient.Instance.GetRaw("/api/ml/models",
                json =>
                {
                    try
                    {
                        var models = JsonConvert.DeserializeObject<List<MlModel>>(json);
                        foreach (var m in models)
                        {
                            var row = Instantiate(historyRowPrefab, historyParent);
                            var texts = row.GetComponentsInChildren<TMP_Text>();
                            if (texts.Length > 0) texts[0].text = $"v{m.version}";
                            if (texts.Length > 1) texts[1].text = $"Acc: {m.accuracy:P1}";
                            if (texts.Length > 2) texts[2].text = m.trained_at;
                        }
                    }
                    catch (Exception e) { ShowError($"History parse error: {e.Message}"); }
                },
                err => ShowError($"History load failed: {err}"));
        }

        // ── Training ─────────────────────────────────────────────────────
        private void OnStartTraining()
        {
            if (_isTraining) return;
            _isTraining = true;
            startTrainingButton.interactable = false;
            stopTrainingButton.interactable  = true;
            statusText.text = "Training started...";
            _accuracyHistory.Clear();
            _lossHistory.Clear();
            AppendLog("[Training] Session started.");

            ApiClient.Instance.PostRaw("/api/ml/train", "{}",
                json =>
                {
                    AppendLog($"[Training] {json}");
                    _pollCoroutine = StartCoroutine(PollTrainingStatus());
                },
                err =>
                {
                    _isTraining = false;
                    startTrainingButton.interactable = true;
                    stopTrainingButton.interactable  = false;
                    ShowError($"Start training failed: {err}");
                });
        }

        private void OnStopTraining()
        {
            if (_pollCoroutine != null) { StopCoroutine(_pollCoroutine); _pollCoroutine = null; }
            _isTraining = false;
            startTrainingButton.interactable = true;
            stopTrainingButton.interactable  = false;
            statusText.text = "Training stopped.";
            AppendLog("[Training] Session stopped by user.");
        }

        private IEnumerator PollTrainingStatus()
        {
            while (_isTraining)
            {
                yield return new WaitForSeconds(PollInterval);
                ApiClient.Instance.GetRaw("/api/ml/train",
                    json =>
                    {
                        try
                        {
                            var status = JsonConvert.DeserializeObject<TrainingStatus>(json);
                            statusText.text = $"Epoch {status.epoch}/{status.total_epochs} — Acc: {status.accuracy:P1} Loss: {status.loss:F4}";
                            _accuracyHistory.Add(status.accuracy);
                            _lossHistory.Add(status.loss);
                            RedrawChart(accuracyChartRect, _accuracyHistory, Color.green);
                            RedrawChart(lossChartRect,     _lossHistory,     Color.red);
                            accuracyLabel.text = $"Accuracy: {status.accuracy:P1}";
                            lossLabel.text     = $"Loss: {status.loss:F4}";
                            AppendLog($"[Epoch {status.epoch}] acc={status.accuracy:P1} loss={status.loss:F4}");

                            if (status.finished)
                            {
                                _isTraining = false;
                                startTrainingButton.interactable = true;
                                stopTrainingButton.interactable  = false;
                                statusText.text = "Training complete!";
                                AppendLog("[Training] Finished.");
                                LoadStats();
                                LoadModelHistory();
                                if (status.feature_importance != null)
                                    RenderFeatureImportance(status.feature_importance);
                            }
                        }
                        catch (Exception e) { AppendLog($"[Poll error] {e.Message}"); }
                    },
                    err => AppendLog($"[Poll failed] {err}"));
            }
        }

        // ── Export Model ─────────────────────────────────────────────────
        private void OnExportModel()
        {
            exportModelButton.interactable = false;
            statusText.text = "Exporting model...";
            ApiClient.Instance.PostRaw("/api/ml/models/export", "{}",
                _ =>
                {
                    exportModelButton.interactable = true;
                    statusText.text = "Model exported.";
                    AppendLog("[Export] Model exported successfully.");
                },
                err =>
                {
                    exportModelButton.interactable = true;
                    ShowError($"Export failed: {err}");
                });
        }

        // ── Feature Importance Chart ──────────────────────────────────────
        private void RenderFeatureImportance(Dictionary<string, float> importance)
        {
            foreach (Transform t in featureBarParent) Destroy(t.gameObject);
            float max = 0.001f;
            foreach (var v in importance.Values) if (v > max) max = v;

            foreach (var kvp in importance)
            {
                var bar = Instantiate(featureBarPrefab, featureBarParent);
                var texts = bar.GetComponentsInChildren<TMP_Text>();
                if (texts.Length > 0) texts[0].text = kvp.Key;
                var fill = bar.transform.Find("Fill");
                if (fill != null)
                {
                    var rt = fill.GetComponent<RectTransform>();
                    if (rt != null) rt.anchorMax = new Vector2(kvp.Value / max, 1f);
                }
                if (texts.Length > 1) texts[1].text = $"{kvp.Value:F3}";
            }
        }

        // ── Line Chart (simple UI Image-based sparkline) ──────────────────
        private void RedrawChart(RectTransform container, List<float> values, Color color)
        {
            // Remove old points
            foreach (Transform t in container) Destroy(t.gameObject);
            if (values.Count < 2) return;

            float min = float.MaxValue, max = float.MinValue;
            foreach (var v in values) { if (v < min) min = v; if (v > max) max = v; }
            if (Mathf.Approximately(min, max)) max = min + 1f;

            float w = container.rect.width;
            float h = container.rect.height;

            for (int i = 0; i < values.Count; i++)
            {
                var dot = new GameObject("Dot");
                dot.transform.SetParent(container, false);
                var img = dot.AddComponent<Image>();
                img.color = color;
                var rt = dot.GetComponent<RectTransform>();
                rt.sizeDelta = new Vector2(6, 6);
                float xRatio = (float)i / (values.Count - 1);
                float yRatio = (values[i] - min) / (max - min);
                rt.anchoredPosition = new Vector2(xRatio * w - w * 0.5f, yRatio * h - h * 0.5f);
            }
        }

        // ── Log ───────────────────────────────────────────────────────────
        private void AppendLog(string line)
        {
            logText.text += line + "\n";
            Canvas.ForceUpdateCanvases();
            logScrollRect.verticalNormalizedPosition = 0f;
        }

        private void OnBack()
        {
            if (_pollCoroutine != null) StopCoroutine(_pollCoroutine);
            SceneManager.LoadScene("MainMenu");
        }

        private void ShowError(string msg)
        {
            errorText.text = msg;
            errorPanel.SetActive(true);
            Debug.LogWarning($"[TrainingController] {msg}");
        }

        // ── Data models ───────────────────────────────────────────────────
        [Serializable] private class MlStats
        {
            public int    card_count;
            public int    session_count;
            public string model_version;
            public string last_trained;
        }

        [Serializable] private class MlModel
        {
            public string version;
            public float  accuracy;
            public string trained_at;
        }

        [Serializable] private class TrainingStatus
        {
            public int    epoch;
            public int    total_epochs;
            public float  accuracy;
            public float  loss;
            public bool   finished;
            public Dictionary<string, float> feature_importance;
        }
    }
}
