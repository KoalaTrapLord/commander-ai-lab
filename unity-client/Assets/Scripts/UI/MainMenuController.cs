using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using TMPro;
using CommanderAILab.Services;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Main menu scene controller. Handles server URL config,
    /// connection health check, and navigation to sub-scenes.
    /// </summary>
    public class MainMenuController : MonoBehaviour
    {
        [Header("Server Config")]
        [SerializeField] private TMP_InputField serverUrlInput;
        [SerializeField] private Button connectButton;
        [SerializeField] private Image statusIndicator;
        [SerializeField] private TMP_Text statusText;

        [Header("Navigation Buttons")]
        [SerializeField] private Button collectionButton;
        [SerializeField] private Button deckBuilderButton;
        [SerializeField] private Button deckGenButton;
        [SerializeField] private Button simulatorButton;
        [SerializeField] private Button scannerButton;
        [SerializeField] private Button coachButton;
        [SerializeField] private Button trainingButton;

        [Header("Error Panel")]
        [SerializeField] private GameObject errorPanel;
        [SerializeField] private TMP_Text errorText;
        [SerializeField] private Button retryButton;

        private readonly Color green = new Color(0.2f, 0.8f, 0.2f);
        private readonly Color red = new Color(0.8f, 0.2f, 0.2f);
        private readonly Color yellow = new Color(0.8f, 0.8f, 0.2f);
        private bool isConnected;

        private void Start()
        {
            serverUrlInput.text = ApiClient.Instance.BaseUrl;
            connectButton.onClick.AddListener(OnConnect);
            retryButton.onClick.AddListener(OnConnect);

            collectionButton.onClick.AddListener(() => LoadScene("Collection"));
            deckBuilderButton.onClick.AddListener(() => LoadScene("DeckBuilder"));
            deckGenButton.onClick.AddListener(() => LoadScene("DeckGenerator"));
            simulatorButton.onClick.AddListener(() => LoadScene("Simulator"));
            scannerButton.onClick.AddListener(() => LoadScene("Scanner"));
            coachButton.onClick.AddListener(() => LoadScene("Coach"));
            trainingButton.onClick.AddListener(() => LoadScene("Training"));

            SetNavEnabled(false);
            errorPanel.SetActive(false);
            OnConnect();
        }

        private void OnConnect()
        {
            ApiClient.Instance.BaseUrl = serverUrlInput.text;
            statusIndicator.color = yellow;
            statusText.text = "Connecting...";
            errorPanel.SetActive(false);

            ApiClient.Instance.HealthCheck(alive =>
            {
                isConnected = alive;
                statusIndicator.color = alive ? green : red;
                statusText.text = alive ? "Connected" : "Disconnected";
                SetNavEnabled(alive);
                if (!alive) ShowError("Cannot reach server at " + ApiClient.Instance.BaseUrl);
            });
        }

        private void SetNavEnabled(bool enabled)
        {
            collectionButton.interactable = enabled;
            deckBuilderButton.interactable = enabled;
            deckGenButton.interactable = enabled;
            simulatorButton.interactable = enabled;
            scannerButton.interactable = enabled;
            coachButton.interactable = enabled;
            trainingButton.interactable = enabled;
        }

        private void ShowError(string msg)
        {
            errorPanel.SetActive(true);
            errorText.text = msg;
        }

        private void LoadScene(string sceneName)
        {
            if (isConnected) SceneManager.LoadScene(sceneName);
        }
    }
}
