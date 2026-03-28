using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using CommanderAILab.Models;

namespace CommanderAILab.UI
{
    /// <summary>
    /// Token creation and tracking panel in the BattlefieldCenter.
    /// Human creates tokens manually; AI tokens are added via AddToken() from server events.
    /// </summary>
    public class TokenPanelController : MonoBehaviour
    {
        [Header("Creation Row")]
        [SerializeField] private TMP_InputField nameInput;
        [SerializeField] private TMP_InputField powerInput;
        [SerializeField] private TMP_InputField toughnessInput;
        [SerializeField] private TMP_InputField qtyInput;
        [SerializeField] private Button         createBtn;

        [Header("List")]
        [SerializeField] private Transform  tokenListParent;
        [SerializeField] private GameObject tokenRowPrefab;

        private readonly List<TokenModel>   _tokens    = new();
        private readonly List<TokenRowView> _rowViews  = new();

        // ── Lifecycle ───────────────────────────────────────────
        private void Start() => createBtn.onClick.AddListener(OnCreateToken);

        // ── Token management ────────────────────────────────────
        private void OnCreateToken()
        {
            string tokenName = nameInput?.text?.Trim();
            if (string.IsNullOrEmpty(tokenName)) return;

            int.TryParse(qtyInput?.text, out int qty);
            qty = Mathf.Max(1, qty);

            var token = new TokenModel
            {
                id         = Guid.NewGuid().ToString(),
                name       = tokenName,
                power      = powerInput?.text?.Trim() ?? "",
                toughness  = toughnessInput?.text?.Trim() ?? "",
                ownerSeat  = 0,
                qty        = qty
            };

            AddToken(token);

            // Clear inputs
            if (nameInput)      nameInput.text      = "";
            if (powerInput)     powerInput.text     = "";
            if (toughnessInput) toughnessInput.text = "";
            if (qtyInput)       qtyInput.text       = "1";
        }

        public void AddToken(TokenModel token)
        {
            _tokens.Add(token);
            var go   = Instantiate(tokenRowPrefab, tokenListParent);
            var view = go.GetComponent<TokenRowView>();
            if (view != null)
            {
                view.Bind(token, RemoveToken);
                _rowViews.Add(view);
            }
        }

        private void RemoveToken(TokenModel token)
        {
            int idx = _tokens.IndexOf(token);
            if (idx < 0) return;

            _tokens.RemoveAt(idx);
            var view = _rowViews[idx];
            _rowViews.RemoveAt(idx);
            if (view != null) Destroy(view.gameObject);
        }

        public IReadOnlyList<TokenModel> Tokens => _tokens;
    }
}
