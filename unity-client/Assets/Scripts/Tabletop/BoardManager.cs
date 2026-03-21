using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// Manages the 3D tabletop layout: places CardObject3D instances into
    /// player zones (battlefield, hand, command zone, graveyard).
    ///
    /// Layout: 4-player Commander table viewed from above.
    ///   Seat 0 (You):     Bottom  (near camera)
    ///   Seat 1 (AI-Aggro): Right
    ///   Seat 2 (AI-Control): Top   (far from camera)
    ///   Seat 3 (AI-Combo): Left
    /// </summary>
    public class BoardManager : MonoBehaviour
    {
        [Header("Zone Anchors (set in editor or auto-generated)")]
        [SerializeField] private Transform[] battlefieldAnchors = new Transform[4];
        [SerializeField] private Transform[] handAnchors = new Transform[4];
        [SerializeField] private Transform[] commandZoneAnchors = new Transform[4];
        [SerializeField] private Transform[] graveyardAnchors = new Transform[4];

        [Header("Layout Settings")]
        [SerializeField] private float cardSpacingX = 0.75f;
        [SerializeField] private float cardSpacingZ = 1.0f;
        [SerializeField] private int maxCardsPerRow = 8;
        [SerializeField] private float handFanAngle = 5f;
        [SerializeField] private float handCardSpacing = 0.55f;

        [Header("Table")]
        [SerializeField] private float tableRadius = 5f;

        // Card tracking
        private readonly Dictionary<int, CardObject3D> _activeCards = new();
        private GameStateResponse _lastState;

        // Selection
        public CardObject3D SelectedCard { get; private set; }
        public event System.Action<CardObject3D> OnCardSelected;
        public event System.Action<CardObject3D> OnCardDeselected;

        // Hover tracking
        private CardObject3D _hoveredCard;
        private Camera _mainCamera;

        private void Start()
        {
            _mainCamera = Camera.main;
            if (battlefieldAnchors[0] == null)
                CreateDefaultAnchors();
        }

        // ── Anchor Generation ──────────────────────────────────────

        /// <summary>Creates default zone anchors for a 4-player table.</summary>
        public void CreateDefaultAnchors()
        {
            // Positions relative to table center (0,0,0)
            // Seat 0: South (player), Seat 1: East, Seat 2: North, Seat 3: West
            Vector3[] seatPositions =
            {
                new Vector3(0, 0, -tableRadius * 0.5f),   // South
                new Vector3(tableRadius * 0.5f, 0, 0),    // East
                new Vector3(0, 0, tableRadius * 0.5f),     // North
                new Vector3(-tableRadius * 0.5f, 0, 0),   // West
            };

            float[] seatRotationsY = { 0f, 90f, 180f, 270f };

            for (int i = 0; i < 4; i++)
            {
                float rot = seatRotationsY[i];
                Vector3 pos = seatPositions[i];
                Vector3 forward = Quaternion.Euler(0, rot, 0) * Vector3.forward;

                // Battlefield: center of player's area
                battlefieldAnchors[i] = CreateAnchor($"Battlefield_Seat{i}",
                    pos, rot);

                // Hand: behind battlefield (closer to player edge)
                handAnchors[i] = CreateAnchor($"Hand_Seat{i}",
                    pos - forward * 1.8f, rot);

                // Command zone: to the right of battlefield
                commandZoneAnchors[i] = CreateAnchor($"CommandZone_Seat{i}",
                    pos + Quaternion.Euler(0, rot, 0) * Vector3.right * 2.5f, rot);

                // Graveyard: to the left of battlefield
                graveyardAnchors[i] = CreateAnchor($"Graveyard_Seat{i}",
                    pos + Quaternion.Euler(0, rot, 0) * Vector3.left * 2.5f, rot);
            }
        }

        private Transform CreateAnchor(string name, Vector3 position, float yRotation)
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform);
            go.transform.localPosition = position;
            go.transform.localRotation = Quaternion.Euler(0, yRotation, 0);
            return go.transform;
        }

        // ── State Sync ─────────────────────────────────────────────

        /// <summary>
        /// Sync the board to match a new GameStateResponse.
        /// Creates, moves, or destroys CardObject3D instances as needed.
        /// </summary>
        public void SyncToState(GameStateResponse state)
        {
            if (state == null) return;
            _lastState = state;

            HashSet<int> seenIds = new();

            foreach (var player in state.players)
            {
                // Battlefield
                LayoutZone(player.battlefield, battlefieldAnchors[player.seat],
                    player.seat, seenIds, faceUp: true, grid: true);

                // Hand (only human hand has cards; AI hands are empty in the DTO)
                LayoutZone(player.hand, handAnchors[player.seat],
                    player.seat, seenIds, faceUp: player.isHuman, grid: false);

                // Command zone
                LayoutZone(player.commandZone, commandZoneAnchors[player.seat],
                    player.seat, seenIds, faceUp: true, grid: false);

                // Graveyard (show top card only)
                if (player.graveyard != null && player.graveyard.Count > 0)
                {
                    var topGrave = new List<BoardCard> { player.graveyard[^1] };
                    LayoutZone(topGrave, graveyardAnchors[player.seat],
                        player.seat, seenIds, faceUp: true, grid: false);
                }
            }

            // Remove cards no longer in any zone
            var toRemove = _activeCards.Keys.Where(id => !seenIds.Contains(id)).ToList();
            foreach (var id in toRemove)
            {
                if (_activeCards.TryGetValue(id, out var card))
                {
                    Destroy(card.gameObject);
                    _activeCards.Remove(id);
                }
            }
        }

        private void LayoutZone(List<BoardCard> cards, Transform anchor,
            int seat, HashSet<int> seenIds, bool faceUp, bool grid)
        {
            if (cards == null || anchor == null) return;

            for (int i = 0; i < cards.Count; i++)
            {
                var data = cards[i];
                seenIds.Add(data.id);

                var cardObj = GetOrCreateCard(data);

                // Calculate position in zone
                Vector3 localPos;
                if (grid)
                {
                    int col = i % maxCardsPerRow;
                    int row = i / maxCardsPerRow;
                    localPos = new Vector3(
                        (col - maxCardsPerRow / 2f + 0.5f) * cardSpacingX,
                        0.01f * row, // slight Y offset per row
                        row * cardSpacingZ
                    );
                }
                else
                {
                    // Fan layout for hand
                    float offset = (i - cards.Count / 2f + 0.5f) * handCardSpacing;
                    localPos = new Vector3(offset, 0.01f * i, 0);
                }

                // Convert to world space via anchor
                Vector3 worldPos = anchor.TransformPoint(localPos);
                cardObj.SetTargetPosition(worldPos);

                // Rotation: face the seat direction + tapped offset
                cardObj.transform.rotation = anchor.rotation;
                cardObj.SetTapped(data.tapped);

                // Flip face-down cards
                if (!faceUp)
                {
                    cardObj.transform.localScale = new Vector3(1, 1, 1);
                    // TODO: show card back instead — for now just keep face up
                }
            }
        }

        private CardObject3D GetOrCreateCard(BoardCard data)
        {
            if (_activeCards.TryGetValue(data.id, out var existing))
            {
                // Update data if changed
                existing.SetTapped(data.tapped);
                return existing;
            }

            var go = new GameObject($"Card_{data.name}_{data.id}");
            go.transform.SetParent(transform);
            var cardObj = go.AddComponent<CardObject3D>();
            cardObj.Initialize(data);
            _activeCards[data.id] = cardObj;
            return cardObj;
        }

        // ── Raycasting / Interaction ────────────────────────────────

        private void Update()
        {
            HandleHover();
            HandleClick();
        }

        private void HandleHover()
        {
            if (_mainCamera == null) return;

            Ray ray = _mainCamera.ScreenPointToRay(Input.mousePosition);
            CardObject3D hitCard = null;

            if (Physics.Raycast(ray, out RaycastHit hit, 100f))
            {
                hitCard = hit.collider.GetComponentInParent<CardObject3D>();
            }

            if (hitCard != _hoveredCard)
            {
                _hoveredCard?.OnHoverExit();
                _hoveredCard = hitCard;
                _hoveredCard?.OnHoverEnter();
            }
        }

        private void HandleClick()
        {
            if (!Input.GetMouseButtonDown(0)) return;
            if (_hoveredCard == null)
            {
                if (SelectedCard != null)
                {
                    SelectedCard.SetSelected(false);
                    OnCardDeselected?.Invoke(SelectedCard);
                    SelectedCard = null;
                }
                return;
            }

            if (SelectedCard == _hoveredCard)
            {
                // Deselect
                SelectedCard.SetSelected(false);
                OnCardDeselected?.Invoke(SelectedCard);
                SelectedCard = null;
            }
            else
            {
                // Select new card
                SelectedCard?.SetSelected(false);
                SelectedCard = _hoveredCard;
                SelectedCard.SetSelected(true);
                OnCardSelected?.Invoke(SelectedCard);
            }
        }

        // ── Utility ─────────────────────────────────────────────────

        public CardObject3D GetCardById(int cardId)
        {
            _activeCards.TryGetValue(cardId, out var card);
            return card;
        }

        public List<CardObject3D> GetCardsForSeat(int seat)
        {
            return _activeCards.Values
                .Where(c => c.OwnerSeat == seat)
                .ToList();
        }

        public void ClearBoard()
        {
            foreach (var kvp in _activeCards)
                if (kvp.Value != null) Destroy(kvp.Value.gameObject);
            _activeCards.Clear();
        }
    }
}
