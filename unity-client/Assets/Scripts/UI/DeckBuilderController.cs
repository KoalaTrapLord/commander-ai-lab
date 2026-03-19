using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
    using UnityEngine.Networking;
using TMPro;
using Newtonsoft.Json;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
  /// <summary>
  /// DeckBuilder scene — deck list, card search, drag-to-add, mana curve,
  /// color-identity pie, save/delete, export to Simulator.
  /// </summary>
  public class DeckBuilderController : MonoBehaviour
  {
    // ── Navigation ───────────────────────────────────────────────────────
    [Header("Navigation")]
    [SerializeField] private Button backButton;
    [SerializeField] private Button exportToSimButton;

    // ── Deck List Panel (left) ────────────────────────────────────────────
    [Header("Deck List Panel")]
    [SerializeField] private Transform    deckListParent;
    [SerializeField] private GameObject   deckRowPrefab;
    [SerializeField] private Button       newDeckButton;
    [SerializeField] private TMP_InputField deckNameInput;

    // ── Active Deck Panel (center) ────────────────────────────────────────
    [Header("Active Deck")]
    [SerializeField] private TMP_Text     deckTitleText;
    [SerializeField] private TMP_Text     cardCountText;       // "99 / 100"
    [SerializeField] private GameObject   validationIndicator; // green/red
    [SerializeField] private TMP_Text     validationText;
    [SerializeField] private Transform    deckCardListParent;
    [SerializeField] private GameObject   deckCardRowPrefab;
    [SerializeField] private Button       saveDeckButton;
    [SerializeField] private Button       deleteDeckButton;

    // ── Commander search ──────────────────────────────────────────────────
    [Header("Commander Search")]
    [SerializeField] private TMP_InputField commanderSearchInput;
    [SerializeField] private Button         commanderSearchButton;
    [SerializeField] private TMP_Dropdown   colorIdentityDropdown;
    [SerializeField] private Transform      commanderResultParent;
    [SerializeField] private GameObject     commanderResultRowPrefab;
    [SerializeField] private TMP_Text       selectedCommanderText;

    // ── Card Search Panel (right) ─────────────────────────────────────────
    [Header("Card Search Panel")]
    [SerializeField] private TMP_InputField cardSearchInput;
    [SerializeField] private Button         cardSearchButton;
    [SerializeField] private Transform      cardSearchResultParent;
    [SerializeField] private GameObject     cardSearchRowPrefab;

    // ── Mana Curve Chart ──────────────────────────────────────────────────
    [Header("Mana Curve")]
    [SerializeField] private Transform manaCurveBarParent;  // holds bar GameObjects
    [SerializeField] private GameObject manaCurveBarPrefab;

    // ── Color Identity Pie ────────────────────────────────────────────────
    [Header("Color Pie")]
    [SerializeField] private Image[] colorPieSlices;  // W U B R G C — 6 images

    // ── Error ─────────────────────────────────────────────────────────────
    [Header("Error")]
    [SerializeField] private GameObject errorPanel;
    [SerializeField] private TMP_Text   errorText;
    [SerializeField] private Button     retryButton;

    // ── State ─────────────────────────────────────────────────────────────
    private List<DeckModel>  _decks       = new();
    private DeckModel        _activeDeck;
    private List<CardModel>  _deckCards   = new();
    private CardModel        _commander;
    private bool             _isDirty;

    private readonly List<GameObject> _deckRowObjects        = new();
    private readonly List<GameObject> _deckCardRowObjects    = new();
    private readonly List<GameObject> _searchRowObjects      = new();
    private readonly List<GameObject> _commanderRowObjects   = new();

    // ── Lifecycle ─────────────────────────────────────────────────────────
    private void Start()
    {
      backButton.onClick.AddListener(() =>
      {
        if (_isDirty) PromptSave();
        else SceneManager.LoadScene("MainMenu");
      });

      exportToSimButton.onClick.AddListener(OnExportToSim);
      newDeckButton.onClick.AddListener(OnNewDeck);
      saveDeckButton.onClick.AddListener(OnSaveDeck);
      deleteDeckButton.onClick.AddListener(OnDeleteDeck);

      cardSearchButton.onClick.AddListener(OnCardSearch);
      cardSearchInput.onSubmit.AddListener(_ => OnCardSearch());

      commanderSearchButton.onClick.AddListener(OnCommanderSearch);
      commanderSearchInput.onSubmit.AddListener(_ => OnCommanderSearch());

      retryButton.onClick.AddListener(LoadDecks);
      errorPanel.SetActive(false);

      // Pick up any card passed from Collection scene
      string pending = PlayerPrefs.GetString("PendingAddCard", "");
      if (!string.IsNullOrEmpty(pending))
      {
        PlayerPrefs.DeleteKey("PendingAddCard");
        try
        {
          var card = JsonConvert.DeserializeObject<CardModel>(pending);
          if (card != null) AddCardToDeck(card);
        }
        catch { }
      }

      LoadDecks();
    }

    // ── Deck List ─────────────────────────────────────────────────────────
    private void LoadDecks()
    {
      errorPanel.SetActive(false);
      ApiClient.Instance.GetDecks(
        json =>
        {
          try
          {
            var wrapper = JsonConvert.DeserializeObject<DecksWrapper>(json);
            _decks = wrapper?.decks ?? new List<DeckModel>();
          }
          catch { _decks = new List<DeckModel>(); }
          RebuildDeckList();
        },
        err => ShowError($"Failed to load decks:\n{err}"));
    }

    private void RebuildDeckList()
    {
      foreach (var go in _deckRowObjects) if (go) Destroy(go);
      _deckRowObjects.Clear();

      foreach (var deck in _decks)
      {
        var row = Instantiate(deckRowPrefab, deckListParent);
        _deckRowObjects.Add(row);
        var label = row.GetComponentInChildren<TMP_Text>();
        if (label) label.text = deck.name;
        var btn = row.GetComponentInChildren<Button>();
        var captured = deck;
        if (btn) btn.onClick.AddListener(() => LoadActiveDeck(captured));
      }
    }

    private void LoadActiveDeck(DeckModel deck)
    {
      _activeDeck = deck;
      _deckCards  = deck.cards ?? new List<CardModel>();
      _isDirty    = false;
      RebuildDeckCardList();
      RefreshCharts();
    }

    // ── Active Deck Cards ─────────────────────────────────────────────────
    private void RebuildDeckCardList()
    {
      foreach (var go in _deckCardRowObjects) if (go) Destroy(go);
      _deckCardRowObjects.Clear();

      if (_activeDeck == null) return;
      deckTitleText.text = _activeDeck.name;
      UpdateCardCount();

      foreach (var card in _deckCards)
      {
        var row = Instantiate(deckCardRowPrefab, deckCardListParent);
        _deckCardRowObjects.Add(row);

        var labels = row.GetComponentsInChildren<TMP_Text>();
        if (labels.Length > 0) labels[0].text = card.name;
        if (labels.Length > 1) labels[1].text = card.manaCost;

        var btns = row.GetComponentsInChildren<Button>();
        var captured = card;
        // +/- buttons (assumed order: remove)
        if (btns.Length > 0) btns[0].onClick.AddListener(() => RemoveCardFromDeck(captured));
      }
    }

    private void AddCardToDeck(CardModel card)
    {
      if (_activeDeck == null) { ShowError("Select or create a deck first."); return; }
      _deckCards.Add(card);
      _isDirty = true;
      RebuildDeckCardList();
      RefreshCharts();
    }

    private void RemoveCardFromDeck(CardModel card)
    {
      _deckCards.Remove(card);
      _isDirty = true;
      RebuildDeckCardList();
      RefreshCharts();
    }

    private void UpdateCardCount()
    {
      int count = _deckCards.Count;
      cardCountText.text = $"{count} / 100";
      bool valid = count == 100 || count == 99; // 99 + commander
      validationIndicator.GetComponent<Image>().color = valid
        ? new Color(0.2f, 0.7f, 0.2f) : new Color(0.7f, 0.2f, 0.2f);
      validationText.text = valid ? "Valid deck" : $"{100 - count} cards needed";
    }

    // ── Card Search (right panel) ─────────────────────────────────────────
    private void OnCardSearch()
    {
      string q = cardSearchInput.text.Trim();
      if (string.IsNullOrEmpty(q)) return;
      ApiClient.Instance.GetCollection(
        json => PopulateCardSearchResults(json),
        err  => ShowError($"Search failed:\n{err}"),
        search: q);
    }

    private void PopulateCardSearchResults(string json)
    {
      foreach (var go in _searchRowObjects) if (go) Destroy(go);
      _searchRowObjects.Clear();

      List<CardModel> cards;
      try
      {
        var resp = JsonConvert.DeserializeObject<CollectionResponse>(json);
        cards = resp?.cards ?? new List<CardModel>();
      }
      catch { return; }

      foreach (var card in cards)
      {
        var row = Instantiate(cardSearchRowPrefab, cardSearchResultParent);
        _searchRowObjects.Add(row);
        var label = row.GetComponentInChildren<TMP_Text>();
        if (label) label.text = $"{card.name}  {card.manaCost}";
        var btn = row.GetComponentInChildren<Button>();
        var captured = card;
        if (btn) btn.onClick.AddListener(() => AddCardToDeck(captured));
      }
    }

    // ── Commander Search ──────────────────────────────────────────────────
    private void OnCommanderSearch()
    {
      string q = commanderSearchInput.text.Trim();
      string color = colorIdentityDropdown.value > 0
        ? colorIdentityDropdown.options[colorIdentityDropdown.value].text : "";
      string path = $"/api/collection?search={UnityWebRequest.EscapeURL(q)}&type=Legendary+Creature";
      if (!string.IsNullOrEmpty(color))
        path += $"&colors={UnityWebRequest.EscapeURL(color)}";

      StartCoroutine(ApiClient.Instance.GetRaw(path,
        json => PopulateCommanderResults(json),
        err  => ShowError($"Commander search failed:\n{err}")));
    }

    private void PopulateCommanderResults(string json)
    {
      foreach (var go in _commanderRowObjects) if (go) Destroy(go);
      _commanderRowObjects.Clear();

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
        _commanderRowObjects.Add(row);
        var label = row.GetComponentInChildren<TMP_Text>();
        if (label) label.text = card.name;
        var btn = row.GetComponentInChildren<Button>();
        var captured = card;
        if (btn) btn.onClick.AddListener(() => SelectCommander(captured));
      }
    }

    private void SelectCommander(CardModel card)
    {
      _commander = card;
      selectedCommanderText.text = $"Commander: {card.name}";
      if (_activeDeck != null) _activeDeck.commanderName = card.name;
      _isDirty = true;
    }

    // ── Save / Delete ─────────────────────────────────────────────────────
    private void OnNewDeck()
    {
      string name = deckNameInput.text.Trim();
      if (string.IsNullOrEmpty(name)) name = "New Deck";
      var newDeck = new DeckModel { name = name, cards = new List<CardModel>() };
      string json = JsonConvert.SerializeObject(newDeck);
      ApiClient.Instance.CreateDeck(json,
        _ => LoadDecks(),
        err => ShowError($"Create deck failed:\n{err}"));
    }

    private void OnSaveDeck()
    {
      if (_activeDeck == null) return;
      _activeDeck.cards = _deckCards;
      string json = JsonConvert.SerializeObject(_activeDeck);
      string path = $"/api/decks/{_activeDeck.id}";
      StartCoroutine(ApiClient.Instance.PatchRaw(path, json,
        _ => { _isDirty = false; LoadDecks(); },
        err => ShowError($"Save failed:\n{err}")));
    }

    private void OnDeleteDeck()
    {
      if (_activeDeck == null) return;
      StartCoroutine(ApiClient.Instance.Delete($"/api/decks/{_activeDeck.id}",
        _ => { _activeDeck = null; _deckCards.Clear(); LoadDecks(); },
        err => ShowError($"Delete failed:\n{err}")));
    }

    // ── Charts ────────────────────────────────────────────────────────────
    private void RefreshCharts()
    {
      BuildManaCurve();
      BuildColorPie();
    }

    private void BuildManaCurve()
    {
      foreach (Transform child in manaCurveBarParent) Destroy(child.gameObject);

      int[] buckets = new int[8]; // 0,1,2,3,4,5,6,7+
      foreach (var card in _deckCards)
      {
        int cmc = Mathf.Clamp(Mathf.RoundToInt(card.cmc), 0, 7);
        buckets[cmc]++;
      }

      int max = 1;
      foreach (int v in buckets) if (v > max) max = v;kets.Length; i++)
            {
                var bar = Instantiate(manaCurveBarPrefab, manaCurveBarParent);
                var rt = bar.GetComponent<RectTransform>();
                float height = (buckets[i] / (float)max) * 120f;
                rt.sizeDelta = new Vector2(rt.sizeDelta.x, height);
                var label = bar.GetComponentInChildren<TMP_Text>();
                if (label) label.text = buckets[i].ToString();
            }
        }

        private void BuildColorPie()
        {
            if (colorPieSlices == null || colorPieSlices.Length == 0) return;

            // Count WUBRGC from mana costs
            int[] counts = new int[6]; // W U B R G C
            foreach (var card in _deckCards)
            {
                string mc = card.manaCost ?? "";
                if (mc.Contains("W")) counts[0]++;
                if (mc.Contains("U")) counts[1]++;
                if (mc.Contains("B")) counts[2]++;
                if (mc.Contains("R")) counts[3]++;
                if (mc.Contains("G")) counts[4]++;
                // colorless: has digits but no WUBRG
                if (!mc.Contains("W") && !mc.Contains("U") && !mc.Contains("B")
                    && !mc.Contains("R") && !mc.Contains("G") && mc.Length > 0)
                    counts[5]++;
            }

            int total = 0;
            foreach (int c in counts) total += c;
            if (total == 0) total = 1;

            for (int i = 0; i < colorPieSlices.Length && i < counts.Length; i++)
            {
                colorPieSlices[i].fillAmount = counts[i] / (float)total;
            }
        }

        // ── Error / Prompt ────────────────────────────────────────────────────
        private void ShowError(string msg)
        {
            errorPanel.SetActive(true);
            errorText.text = msg;
        }

        private void PromptSave()
        {
            // Simple: just save and navigate
            OnSaveDeck();
            SceneManager.LoadScene("MainMenu");
        }

        private void OnExportToSim()
        {
            if (_activeDeck == null) return;
            PlayerPrefs.SetString("SimDeck", JsonConvert.SerializeObject(_activeDeck));
            SceneManager.LoadScene("Simulator");
        }

        // ── Helper Models ─────────────────────────────────────────────────────
        [System.Serializable]
        private class DecksWrapper { public List<DeckModel> decks; }
        [System.Serializable]
        private class CollectionResponse { public List<CardModel> cards; }
    }
}

      for (int i = 0; i < buc
