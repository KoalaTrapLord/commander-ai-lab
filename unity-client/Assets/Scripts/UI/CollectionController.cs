using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
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
  /// Collection scene controller — card grid with search, filter, sort,
  /// card detail panel, async image loading, pagination, and mobile support.
  /// </summary>
  public class CollectionController : MonoBehaviour
  {
    // ── Header ──────────────────────────────────────────────────────────
    [Header("Navigation")]
    [SerializeField] private Button backButton;

    [Header("Search & Sort")]
    [SerializeField] private TMP_InputField searchInput;
    [SerializeField] private TMP_Dropdown  sortDropdown;
    [SerializeField] private Button        searchButton;
    [SerializeField] private Button        filterToggleButton;  // mobile: open/close drawer

    [Header("Filter Sidebar")]
    [SerializeField] private GameObject    filterPanel;         // root – toggled on mobile
    [SerializeField] private TMP_Dropdown  colorFilterDropdown;
    [SerializeField] private TMP_Dropdown  typeFilterDropdown;
    [SerializeField] private TMP_Dropdown  setFilterDropdown;
    [SerializeField] private TMP_Dropdown  rarityFilterDropdown;
    [SerializeField] private TMP_Dropdown  ownedFilterDropdown; // All / Owned / Missing
    [SerializeField] private Button        applyFilterButton;
    [SerializeField] private Button        clearFilterButton;

    [Header("Card Grid")]
    [SerializeField] private Transform     cardGridParent;      // ScrollRect content
    [SerializeField] private GameObject    cardPrefab;          // CardPrefab instance
    [SerializeField] private ScrollRect    gridScrollRect;

    [Header("Pagination")]
    [SerializeField] private Button        loadMoreButton;
    [SerializeField] private TMP_Text      pageInfoText;
    [SerializeField] private GameObject    loadingSpinner;

    [Header("Card Detail Panel")]
    [SerializeField] private GameObject    detailPanel;
    [SerializeField] private Image         detailCardFront;
    [SerializeField] private Image         detailCardBack;      // placeholder / back face
    [SerializeField] private TMP_Text      detailCardName;
    [SerializeField] private TMP_Text      detailManaCost;
    [SerializeField] private TMP_Text      detailType;
    [SerializeField] private TMP_Text      detailRarity;
    [SerializeField] private TMP_Text      detailSet;
    [SerializeField] private TMP_Text      detailOracleText;
    [SerializeField] private TMP_Text      detailQuantity;
    [SerializeField] private Button        detailAddToDeckButton;
    [SerializeField] private Button        detailCloseButton;

    [Header("Error")]
    [SerializeField] private GameObject    errorPanel;
    [SerializeField] private TMP_Text      errorText;
    [SerializeField] private Button        retryButton;

    // ── State ────────────────────────────────────────────────────────────
    private List<CardModel> _cards       = new();
    private CardModel       _selectedCard;
    private int             _currentPage = 1;
    private int             _totalCards  = 0;
    private const int       PageSize     = 40;
    private bool            _isLoading   = false;
    private bool            _filterOpen  = false;

    // Current filter / sort state
    private string _searchQuery   = "";
    private string _colorFilter   = "";
    private string _typeFilter    = "";
    private string _setFilter     = "";
    private string _rarityFilter  = "";
    private string _ownedFilter   = "";   // "all" | "owned" | "missing"
    private string _sortField     = "name";

    // Pooled card tile GameObjects
    private readonly List<GameObject> _cardTiles = new();

    // ── Lifecycle ────────────────────────────────────────────────────────
    private void Start()
    {
      // Back button → MainMenu
      backButton.onClick.AddListener(() => SceneManager.LoadScene("MainMenu"));

      // Search
      searchButton.onClick.AddListener(OnSearchClicked);
      searchInput.onSubmit.AddListener(_ => OnSearchClicked());

      // Sort
      sortDropdown.onValueChanged.AddListener(_ => RefreshFromPage1());

      // Filter actions
      applyFilterButton.onClick.AddListener(RefreshFromPage1);
      clearFilterButton.onClick.AddListener(OnClearFilters);
      filterToggleButton.onClick.AddListener(ToggleFilterPanel);

      // Pagination
      loadMoreButton.onClick.AddListener(OnLoadMore);
      loadMoreButton.gameObject.SetActive(false);

      // Detail panel
      detailCloseButton.onClick.AddListener(CloseDetailPanel);
      detailAddToDeckButton.onClick.AddListener(OnAddToDeck);
      detailPanel.SetActive(false);

      // Error retry
      retryButton.onClick.AddListener(RefreshFromPage1);
      errorPanel.SetActive(false);

      // On mobile start with filter panel hidden
      _filterOpen = Screen.width > 900;
      filterPanel.SetActive(_filterOpen);

      // Initial load
      RefreshFromPage1();
    }

    // ── Search / Filter / Sort ───────────────────────────────────────────
    private void OnSearchClicked()
    {
      _searchQuery = searchInput.text.Trim();
      RefreshFromPage1();
    }

    private void OnClearFilters()
    {
      colorFilterDropdown.value  = 0;
      typeFilterDropdown.value   = 0;
      setFilterDropdown.value    = 0;
      rarityFilterDropdown.value = 0;
      ownedFilterDropdown.value  = 0;
      searchInput.text           = "";
      _searchQuery               = "";
      RefreshFromPage1();
    }

    private void ToggleFilterPanel()
    {
      _filterOpen = !_filterOpen;
      filterPanel.SetActive(_filterOpen);
    }

    // ── Data Loading ─────────────────────────────────────────────────────
    private void RefreshFromPage1()
    {
      _currentPage = 1;
      _cards.Clear();
      ClearCardTiles();
      LoadPage(_currentPage);
    }

    private void OnLoadMore()
    {
      _currentPage++;
      LoadPage(_currentPage);
    }

    private void LoadPage(int page)
    {
      if (_isLoading) return;
      _isLoading = true;
      loadingSpinner.SetActive(true);
      loadMoreButton.interactable = false;
      errorPanel.SetActive(false);

      // Collect filter values from dropdowns
      _colorFilter  = DropdownValue(colorFilterDropdown);
      _typeFilter   = DropdownValue(typeFilterDropdown);
      _setFilter    = DropdownValue(setFilterDropdown);
      _rarityFilter = DropdownValue(rarityFilterDropdown);
      _ownedFilter  = DropdownValue(ownedFilterDropdown);
      _sortField    = SortFieldFromDropdown(sortDropdown.value);

      string path = BuildQueryPath(page);
      StartCoroutine(ApiClient.Instance.GetRaw(path,
        json    => OnPageLoaded(json, page),
        errMsg  => OnLoadError(errMsg)));
    }

    private string BuildQueryPath(int page)
    {
      var sb = new StringBuilder("/api/collection?");
      sb.Append($"page={page}&per_page={PageSize}");
      if (!string.IsNullOrEmpty(_searchQuery))
        sb.Append($"&search={UnityWebRequest.EscapeURL(_searchQuery)}");
      if (!string.IsNullOrEmpty(_colorFilter))
        sb.Append($"&colors={UnityWebRequest.EscapeURL(_colorFilter)}");
      if (!string.IsNullOrEmpty(_typeFilter))
        sb.Append($"&type={UnityWebRequest.EscapeURL(_typeFilter)}");
      if (!string.IsNullOrEmpty(_setFilter))
        sb.Append($"&set={UnityWebRequest.EscapeURL(_setFilter)}");
      if (!string.IsNullOrEmpty(_rarityFilter))
        sb.Append($"&rarity={UnityWebRequest.EscapeURL(_rarityFilter)}");
      if (!string.IsNullOrEmpty(_ownedFilter) && _ownedFilter != "all")
        sb.Append($"&owned={_ownedFilter}");
      if (!string.IsNullOrEmpty(_sortField))
        sb.Append($"&sort={_sortField}");
      return sb.ToString();
    }

    private void OnPageLoaded(string json, int page)
    {
      _isLoading = false;
      loadingSpinner.SetActive(false);

      CollectionResponse response;
      try { response = JsonConvert.DeserializeObject<CollectionResponse>(json); }
      catch (Exception e)
      {
        OnLoadError($"Parse error: {e.Message}");
        return;
      }

      _totalCards = response.total;
      _cards.AddRange(response.cards);

      UpdatePageInfo();
      SpawnCardTiles(response.cards);

      bool hasMore = _cards.Count < _totalCards;
      loadMoreButton.gameObject.SetActive(hasMore);
      loadMoreButton.interactable = true;
    }

    private void OnLoadError(string msg)
    {
      _isLoading = false;
      loadingSpinner.SetActive(false);
      errorText.text = $"Failed to load collection:\n{msg}";
      errorPanel.SetActive(true);
      Debug.LogWarning($"[CollectionController] {msg}");
    }

    // ── Card Tiles ───────────────────────────────────────────────────────
    private void SpawnCardTiles(List<CardModel> cards)
    {
      foreach (var card in cards)
      {
        var tile = Instantiate(cardPrefab, cardGridParent);
        _cardTiles.Add(tile);

        // Set name label (assumes CardPrefab has a TMP child named "CardName")
        var nameLabel = tile.GetComponentInChildren<TMP_Text>();
        if (nameLabel != null) nameLabel.text = card.name;

        // Async image load
        var img = tile.GetComponentInChildren<Image>();
        if (img != null && !string.IsNullOrEmpty(card.imageUrl))
        {
          ImageCache.Instance.GetSprite(card.imageUrl, sprite =>
          {
            if (img != null) img.sprite = sprite;
          });
        }

        // Click → open detail panel
        var btn = tile.GetComponentInChildren<Button>();
        if (btn != null)
        {
          var captured = card;
          btn.onClick.AddListener(() => OpenDetailPanel(captured));
        }
      }
    }

    private void ClearCardTiles()
    {
      foreach (var tile in _cardTiles)
        if (tile != null) Destroy(tile);
      _cardTiles.Clear();
    }

    // ── Detail Panel ─────────────────────────────────────────────────────
    private void OpenDetailPanel(CardModel card)
    {
      _selectedCard = card;
      detailPanel.SetActive(true);

      detailCardName.text  = card.name;
      detailManaCost.text  = card.manaCost;
      detailType.text      = card.typeLine;
      detailRarity.text    = card.rarity;
      detailSet.text       = card.set;
      detailOracleText.text = card.oracleText;
      detailQuantity.text  = $"Owned: {card.ownedQty}";

      // Load card art on front face
      if (!string.IsNullOrEmpty(card.imageUrl))
      {
        ImageCache.Instance.GetSprite(card.imageUrl, sprite =>
        {
          if (detailCardFront != null) detailCardFront.sprite = sprite;
        });
      }

      // Trigger flip animation if the card has an Animator
      var anim = detailPanel.GetComponentInChildren<Animator>();
      anim?.SetTrigger("Flip");
    }

    private void CloseDetailPanel()
    {
      detailPanel.SetActive(false);
      _selectedCard = null;
    }

    // ── Add to Deck ───────────────────────────────────────────────────────
    private void OnAddToDeck()
    {
      if (_selectedCard == null) return;
      // Store selected card in PlayerPrefs for DeckBuilder to pick up
      PlayerPrefs.SetString("PendingAddCard", JsonConvert.SerializeObject(_selectedCard));
      PlayerPrefs.Save();
      SceneManager.LoadScene("DeckBuilder");
    }

    // ── Helpers ───────────────────────────────────────────────────────────
    private void UpdatePageInfo()
    {
      int showing = Mathf.Min(_cards.Count, _totalCards);
      pageInfoText.text = $"Showing {showing} of {_totalCards} cards";
    }

    /// <summary>Returns the option text at index 0 as empty string (means no filter).</summary>
    private static string DropdownValue(TMP_Dropdown dd)
    {
      if (dd.value == 0) return "";
      return dd.options[dd.value].text;
    }

    private static string SortFieldFromDropdown(int idx) => idx switch
    {
      0 => "name",
      1 => "cmc",
      2 => "color",
      3 => "type",
      4 => "price",
      _ => "name"
    };
  }
}
