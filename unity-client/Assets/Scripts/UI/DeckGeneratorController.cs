using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using TMPro;
using Newtonsoft.Json;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
  /// <summary>
  /// DeckGenerator scene — AI deck generation wizard:
  /// commander pick, strategy/budget inputs, precon base,
  /// streaming progress, result preview, save to DeckBuilder.
  /// </summary>
  public class DeckGeneratorController : MonoBehaviour
  {
    // ── Navigation ────────────────────────────────────────────────────
    [Header("Navigation")]
    [SerializeField] private Button backButton;

    // ── Step 1: Commander Selection ───────────────────────────────────
    [Header("Step 1 - Commander")]
    [SerializeField] private TMP_InputField commanderSearchInput;
    [SerializeField] private Button         commanderSearchButton;
    [SerializeField] private Transform      commanderResultParent;
    [SerializeField] private GameObject     commanderResultRowPrefab;
    [SerializeField] private TMP_Text       selectedCommanderLabel;

    // ── Step 2: Strategy & Budget ─────────────────────────────────────
    [Header("Step 2 - Strategy & Budget")]
    [SerializeField] private TMP_Dropdown   strategyDropdown;   // Aggro/Control/Combo/Midrange/Stax/Chaos
    [SerializeField] private TMP_Dropdown   budgetDropdown;     // Pauper/$50/$100/$250/No limit
    [SerializeField] private TMP_InputField synergiesInput;     // free-text themes
    [SerializeField] private TMP_Dropdown   preconBaseDropdown; // optional precon starting point
    [SerializeField] private Toggle         ownedOnlyToggle;    // restrict to owned cards

    // ── Step 3: Generate ──────────────────────────────────────────────
    [Header("Step 3 - Generate")]
    [SerializeField] private Button    generateButton;
    [SerializeField] private GameObject progressPanel;
    [SerializeField] private Slider    progressSlider;
    [SerializeField] private TMP_Text  progressText;

    // ── Step 4: Result Preview ────────────────────────────────────────
    [Header("Step 4 - Result")]
    [SerializeField] private GameObject    resultPanel;
    [SerializeField] private Transform     resultCardListParent;
    [SerializeField] private GameObject    resultCardRowPrefab;
    [SerializeField] private TMP_Text      resultSummaryText;
    [SerializeField] private TMP_Text      resultManaCurveText;
    [SerializeField] private Button        saveToDeckBuilderButton;
    [SerializeField] private Button        regenerateButton;

    // ── Error ─────────────────────────────────────────────────────────
    [Header("Error")]
    [SerializeField] private GameObject errorPanel;
    [SerializeField] private TMP_Text   errorText;
    [SerializeField] private Button     retryButton;

    // ── State ─────────────────────────────────────────────────────────
    private CardModel             _selectedCommander;
    private DeckGenResponse       _lastResult;
    private List<GameObject>      _commanderRows = new();
    private List<GameObject>      _resultRows    = new();
    private List<string>          _preconNames   = new();

    // ── Lifecycle ─────────────────────────────────────────────────────
    private void Start()
    {
      backButton.onClick.AddListener(() => SceneManager.LoadScene("MainMenu"));

      commanderSearchButton.onClick.AddListener(OnCommanderSearch);
      commanderSearchInput.onSubmit.AddListener(_ => OnCommanderSearch());

      generateButton.onClick.AddListener(OnGenerate);
      saveToDeckBuilderButton.onClick.AddListener(OnSaveToDeckBuilder);
      regenerateButton.onClick.AddListener(OnGenerate);
      retryButton.onClick.AddListener(OnGenerate);

      progressPanel.SetActive(false);
      resultPanel.SetActive(false);
      errorPanel.SetActive(false);

      LoadPrecons();
    }

    // ── Precon list ───────────────────────────────────────────────────
    private void LoadPrecons()
    {
      ApiClient.Instance.GetPrecons(
        json =>
        {
          try
          {
            var wrapper = JsonConvert.DeserializeObject<PreconListWrapper>(json);
            _preconNames = wrapper?.precons ?? new List<string>();
          }
          catch { _preconNames = new List<string>(); }

          var options = new List<TMP_Dropdown.OptionData> { new("None (from scratch)") };
          foreach (var p in _preconNames) options.Add(new TMP_Dropdown.OptionData(p));
          preconBaseDropdown.options = options;
          preconBaseDropdown.value = 0;
        },
        err => Debug.LogWarning($"[DeckGen] Could not load precons: {err}"));
    }

    // ── Commander Search ──────────────────────────────────────────────
    private void OnCommanderSearch()
    {
      string q = commanderSearchInput.text.Trim();
      if (string.IsNullOrEmpty(q)) return;
      string path = $"/api/collection?search={UnityWebRequest.EscapeURL(q)}&type=Legendary+Creature&per_page=20";
      StartCoroutine(ApiClient.Instance.GetRaw(path,
        json => PopulateCommanderResults(json),
        err  => ShowError($"Commander search failed:\n{err}")));
    }

    private void PopulateCommanderResults(string json)
    {
      foreach (var go in _commanderRows) if (go) Destroy(go);
      _commanderRows.Clear();

      List<CardModel> cards;
      try
      {
        var resp = JsonConvert.DeserializeObject<CollectionResponse>(json);
        cards = resp?.cards ?? new List<CardModel>();
      }
      catch { return; }

      foreach (var card in cards)
      {
        var row = Instantiate(commanderResultRowPrefab, commanderResultParent);
        _commanderRows.Add(row);
        var label = row.GetComponentInChildren<TMP_Text>();
        if (label) label.text = $"{card.name}  —  {card.manaCost}";
        var btn = row.GetComponentInChildren<Button>();
        var captured = card;
        if (btn) btn.onClick.AddListener(() => SelectCommander(captured));
      }
    }

    private void SelectCommander(CardModel card)
    {
      _selectedCommander = card;
      selectedCommanderLabel.text = $"Commander: {card.name}";
    }

    // ── Generate ──────────────────────────────────────────────────────
    private void OnGenerate()
    {
      if (_selectedCommander == null)
      {
        ShowError("Please select a commander first.");
        return;
      }

      progressPanel.SetActive(true);
      resultPanel.SetActive(false);
      errorPanel.SetActive(false);
      generateButton.interactable = false;
      progressSlider.value = 0f;
      progressText.text = "Sending request…";

      string strategy  = strategyDropdown.options[strategyDropdown.value].text;
      string budget    = budgetDropdown.options[budgetDropdown.value].text;
      string synergies = synergiesInput.text.Trim();
      bool   ownedOnly = ownedOnlyToggle.isOn;
      string precon    = preconBaseDropdown.value > 0
        ? preconBaseDropdown.options[preconBaseDropdown.value].text : "";

      var requestObj = new
      {
        commander  = _selectedCommander.name,
        strategy   = strategy,
        budget     = budget,
        synergies  = synergies,
        owned_only = ownedOnly,
        precon_base = precon
      };

      string requestJson = JsonConvert.SerializeObject(requestObj);
      StartCoroutine(PollGenerate(requestJson));
    }

    private System.Collections.IEnumerator PollGenerate(string requestJson)
    {
      // Show incremental progress while waiting for API
      float fakeProgress = 0f;
      bool  done         = false;
      string resultJson  = null;
      string errorMsg    = null;

      ApiClient.Instance.GenerateDeck(requestJson,
        json => { resultJson = json; done = true; },
        err  => { errorMsg  = err;  done = true; });

      while (!done)
      {
        fakeProgress = Mathf.MoveTowards(fakeProgress, 0.9f, Time.deltaTime * 0.15f);
        progressSlider.value = fakeProgress;
        progressText.text    = $"Generating… {Mathf.RoundToInt(fakeProgress * 100)}%";
        yield return null;
      }

      progressSlider.value = 1f;
      progressText.text    = "Complete!";
      generateButton.interactable = true;
      progressPanel.SetActive(false);

      if (errorMsg != null) { ShowError($"Generation failed:\n{errorMsg}"); yield break; }

      try { _lastResult = JsonConvert.DeserializeObject<DeckGenResponse>(resultJson); }
      catch (Exception e) { ShowError($"Parse error: {e.Message}"); yield break; }

      ShowResult(_lastResult);
    }

    // ── Result ────────────────────────────────────────────────────────
    private void ShowResult(DeckGenResponse result)
    {
      foreach (var go in _resultRows) if (go) Destroy(go);
      _resultRows.Clear();

      resultPanel.SetActive(true);

      int total = result.cards?.Count ?? 0;
      resultSummaryText.text = $"{total} cards generated for {_selectedCommander.name}";

      // Build simple mana curve summary
      int[] buckets = new int[8];
      if (result.cards != null)
        foreach (var card in result.cards)
        {
          int cmc = Mathf.Clamp(Mathf.RoundToInt(card.cmc), 0, 7);
          buckets[cmc]++;
          var row = Instantiate(resultCardRowPrefab, resultCardListParent);
          _resultRows.Add(row);
          var labels = row.GetComponentsInChildren<TMP_Text>();
          if (labels.Length > 0) labels[0].text = card.name;
          if (labels.Length > 1) labels[1].text = card.manaCost;
        }

      var sb = new System.Text.StringBuilder("CMC: ");
      for (int i = 0; i < 8; i++)
        if (buckets[i] > 0) sb.Append($"{i}{(i==7?"+":"")}:{buckets[i]}  ");
      resultManaCurveText.text = sb.ToString();
    }

    // ── Save to DeckBuilder ───────────────────────────────────────────
    private void OnSaveToDeckBuilder()
    {
      if (_lastResult == null) return;
      PlayerPrefs.SetString("GeneratedDeck", JsonConvert.SerializeObject(_lastResult));
      PlayerPrefs.Save();
      SceneManager.LoadScene("DeckBuilder");
    }

    // ── Error ─────────────────────────────────────────────────────────
    private void ShowError(string msg)
    {
      errorText.text = msg;
      errorPanel.SetActive(true);
      Debug.LogWarning($"[DeckGeneratorController] {msg}");
    }
  }
}
