using System;
using System.Collections;
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
  /// Precon browser scene — browse, search, and install preconstructed Commander decks.
  /// Grid display with card images, deck details panel, install/install-all buttons,
  /// and refresh from GitHub functionality.
  /// </summary>
  public class PreconController : MonoBehaviour
  {
    // -- Header ——————————————————————————————————
    [Header("Navigation")]
    [SerializeField] private Button backButton;

    [Header("Search & Filter")]
    [SerializeField] private TMP_InputField searchInput;
    [SerializeField] private TMP_Dropdown colorFilterDropdown;
    [SerializeField] private Button       searchButton;
    [SerializeField] private Button       clearButton;

    [Header("Deck Grid")]
    [SerializeField] private Transform    deckGridParent;
    [SerializeField] private GameObject   deckCardPrefab;
    [SerializeField] private ScrollRect   gridScrollRect;

    [Header("Deck Detail Panel")]
    [SerializeField] private GameObject   detailPanel;
    [SerializeField] private Image        detailCommanderImage;
    [SerializeField] private TMP_Text     detailDeckName;
    [SerializeField] private TMP_Text     detailColorIdentity;
    [SerializeField] private TMP_Text     detailCardCount;
    [SerializeField] private TMP_Text     detailThemeText;
    [SerializeField] private Button       detailInstallButton;
    [SerializeField] private Button       detailCloseButton;

    [Header("Batch Actions")]
    [SerializeField] private Button       installAllButton;
    [SerializeField] private Button       refreshButton;
    [SerializeField] private TMP_Text     statusText;

    [Header("Loading & Error")]
    [SerializeField] private GameObject   loadingSpinner;
    [SerializeField] private GameObject   errorPanel;
    [SerializeField] private TMP_Text     errorText;
    [SerializeField] private Button       retryButton;

    // -- State ——————————————————————————————————
    private List<PreconDeck> _allPrecons = new();
    private List<PreconDeck> _filteredPrecons = new();
    private PreconDeck       _selectedPrecon;
    private bool             _isLoading = false;
    private HashSet<string>  _installedDecks = new();

    // -- Serializable response wrappers ———————————————————
    [Serializable]
    private class PreconListResponse
    {
      public List<PreconDeck> precons;
    }

    [Serializable]
    public class PreconDeck
    {
      public string fileName;
      public string name;
      public string commander;
      public string colorIdentity;
      public int    cardCount;
      public string theme;
      public string imageUrl;
    }

    [Serializable]
    private class InstallRequest
    {
      public string fileName;
    }

    [Serializable]
    private class InstallResponse
    {
      public bool   installed;
      public string deckName;
      public string destination;
      public string message;
    }

    [Serializable]
    private class BatchInstallRequest
    {
      public List<string> fileNames;
    }

    [Serializable]
    private class BatchInstallResponse
    {
      public List<BatchInstallResult> results;
    }

    [Serializable]
    private class BatchInstallResult
    {
      public string fileName;
      public bool   installed;
      public string deckName;
      public string error;
    }

    [Serializable]
    private class RefreshResponse
    {
      public string message;
      public int    total;
    }

    // ========================================================
    // Lifecycle
    // ========================================================

    private void Start()
    {
      backButton.onClick.AddListener(OnBack);
      searchButton.onClick.AddListener(OnSearch);
      clearButton.onClick.AddListener(OnClear);
      retryButton.onClick.AddListener(LoadPrecons);
      installAllButton.onClick.AddListener(OnInstallAll);
      refreshButton.onClick.AddListener(OnRefresh);
      detailInstallButton.onClick.AddListener(OnInstallSelected);
      detailCloseButton.onClick.AddListener(() => detailPanel.SetActive(false));

      if (searchInput != null)
        searchInput.onSubmit.AddListener(_ => OnSearch());

      detailPanel.SetActive(false);
      errorPanel.SetActive(false);

      LoadPrecons();
    }

    // ========================================================
    // Data Loading
    // ========================================================

    private void LoadPrecons()
    {
      if (_isLoading) return;
      _isLoading = true;
      loadingSpinner.SetActive(true);
      errorPanel.SetActive(false);
      statusText.text = "Loading precons...";

      ApiClient.Instance.Get<PreconListResponse>(
        "/api/lab/precons",
        OnPreconsLoaded,
        OnError
      );
    }

    private void OnPreconsLoaded(PreconListResponse response)
    {
      _isLoading = false;
      loadingSpinner.SetActive(false);

      _allPrecons = response.precons ?? new List<PreconDeck>();
      statusText.text = $"{_allPrecons.Count} precon deck(s) available";

      ApplyFilter();
    }

    // ========================================================
    // Search & Filter
    // ========================================================

    private void OnSearch()
    {
      ApplyFilter();
    }

    private void OnClear()
    {
      searchInput.text = "";
      if (colorFilterDropdown != null)
        colorFilterDropdown.value = 0;
      ApplyFilter();
    }

    private void ApplyFilter()
    {
      string query = searchInput.text.Trim().ToLowerInvariant();
      string colorFilter = "";
      if (colorFilterDropdown != null && colorFilterDropdown.value > 0)
        colorFilter = colorFilterDropdown.options[colorFilterDropdown.value].text;

      _filteredPrecons = _allPrecons.FindAll(p =>
      {
        bool matchesSearch = string.IsNullOrEmpty(query)
          || (p.name != null && p.name.ToLowerInvariant().Contains(query))
          || (p.commander != null && p.commander.ToLowerInvariant().Contains(query))
          || (p.theme != null && p.theme.ToLowerInvariant().Contains(query));

        bool matchesColor = string.IsNullOrEmpty(colorFilter)
          || (p.colorIdentity != null && p.colorIdentity.Contains(colorFilter));

        return matchesSearch && matchesColor;
      });

      RenderGrid();
    }

    // ========================================================
    // Grid Rendering
    // ========================================================

    private void RenderGrid()
    {
      // Clear existing children
      for (int i = deckGridParent.childCount - 1; i >= 0; i--)
        Destroy(deckGridParent.GetChild(i).gameObject);

      foreach (var precon in _filteredPrecons)
      {
        var card = Instantiate(deckCardPrefab, deckGridParent);
        var texts = card.GetComponentsInChildren<TMP_Text>(true);
        if (texts.Length > 0) texts[0].text = precon.name ?? precon.fileName;
        if (texts.Length > 1) texts[1].text = precon.commander ?? "";
        if (texts.Length > 2) texts[2].text = precon.colorIdentity ?? "";

        // Installed badge
        bool installed = _installedDecks.Contains(precon.fileName);
        var badge = card.transform.Find("InstalledBadge");
        if (badge != null) badge.gameObject.SetActive(installed);

        // Click to show detail
        var btn = card.GetComponent<Button>() ?? card.AddComponent<Button>();
        var captured = precon;
        btn.onClick.AddListener(() => ShowDetail(captured));

        // Load commander image async
        if (!string.IsNullOrEmpty(precon.imageUrl))
        {
          var img = card.GetComponentInChildren<Image>();
          if (img != null)
            StartCoroutine(LoadImageAsync(precon.imageUrl, img));
        }
      }

      statusText.text = $"Showing {_filteredPrecons.Count} of {_allPrecons.Count} precon(s)";
    }

    private IEnumerator LoadImageAsync(string url, Image target)
    {
      using var request = UnityEngine.Networking.UnityWebRequestTexture.GetTexture(url);
      yield return request.SendWebRequest();
      if (request.result == UnityEngine.Networking.UnityWebRequest.Result.Success)
      {
        var tex = UnityEngine.Networking.DownloadHandlerTexture.GetContent(request);
        target.sprite = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), Vector2.one * 0.5f);
      }
    }

    // ========================================================
    // Detail Panel
    // ========================================================

    private void ShowDetail(PreconDeck precon)
    {
      _selectedPrecon = precon;
      detailPanel.SetActive(true);

      detailDeckName.text = precon.name ?? precon.fileName;
      detailColorIdentity.text = $"Colors: {precon.colorIdentity ?? "N/A"}";
      detailCardCount.text = $"Cards: {precon.cardCount}";
      detailThemeText.text = $"Theme: {precon.theme ?? "N/A"}";

      bool installed = _installedDecks.Contains(precon.fileName);
      detailInstallButton.interactable = !installed;
      detailInstallButton.GetComponentInChildren<TMP_Text>().text =
        installed ? "Installed" : "Install to Forge";

      if (!string.IsNullOrEmpty(precon.imageUrl))
        StartCoroutine(LoadImageAsync(precon.imageUrl, detailCommanderImage));
    }

    // ========================================================
    // Install Actions
    // ========================================================

    private void OnInstallSelected()
    {
      if (_selectedPrecon == null) return;
      detailInstallButton.interactable = false;
      statusText.text = $"Installing {_selectedPrecon.name}...";

      var req = new InstallRequest { fileName = _selectedPrecon.fileName };
      ApiClient.Instance.Post<InstallRequest, InstallResponse>(
        "/api/lab/precons/install", req,
        res =>
        {
          _installedDecks.Add(_selectedPrecon.fileName);
          statusText.text = res.message;
          detailInstallButton.GetComponentInChildren<TMP_Text>().text = "Installed";
          RenderGrid();
        },
        OnError
      );
    }

    private void OnInstallAll()
    {
      var toInstall = _filteredPrecons.FindAll(p => !_installedDecks.Contains(p.fileName));
      if (toInstall.Count == 0)
      {
        statusText.text = "All visible precons already installed.";
        return;
      }

      installAllButton.interactable = false;
      statusText.text = $"Installing {toInstall.Count} precon(s)...";

      var req = new BatchInstallRequest
      {
        fileNames = toInstall.ConvertAll(p => p.fileName)
      };

      ApiClient.Instance.Post<BatchInstallRequest, BatchInstallResponse>(
        "/api/lab/precons/install-batch", req,
        res =>
        {
          int successCount = 0;
          foreach (var r in res.results)
          {
            if (r.installed)
            {
              _installedDecks.Add(r.fileName);
              successCount++;
            }
          }
          statusText.text = $"Installed {successCount} of {res.results.Count} precon(s).";
          installAllButton.interactable = true;
          RenderGrid();
        },
        OnError
      );
    }

    private void OnRefresh()
    {
      refreshButton.interactable = false;
      statusText.text = "Refreshing precon database from GitHub...";
      loadingSpinner.SetActive(true);

      ApiClient.Instance.PostRaw(
        "/api/lab/precons/refresh", "{}",
        json =>
        {
          var res = JsonConvert.DeserializeObject<RefreshResponse>(json);
          statusText.text = res.message;
          refreshButton.interactable = true;
          LoadPrecons();
        },
        err =>
        {
          refreshButton.interactable = true;
          loadingSpinner.SetActive(false);
          OnError(err);
        }
      );
    }

    // ========================================================
    // Navigation
    // ========================================================

    private void OnBack()
    {
      SceneManager.LoadScene("MainMenu");
    }

    // ========================================================
    // Error Handling
    // ========================================================

    private void OnError(string error)
    {
      _isLoading = false;
      loadingSpinner.SetActive(false);
      errorPanel.SetActive(true);
      errorText.text = $"Error: {error}";
      statusText.text = "An error occurred.";
      Debug.LogWarning($"[PreconController] {error}");
    }
  }
}
