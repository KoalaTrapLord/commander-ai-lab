using System.Collections;
using UnityEngine;
using CommanderAILab.Models;
using CommanderAILab.Services;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// 3D card representation on the tabletop.
    /// Creates a quad mesh with Scryfall card art texture.
    /// Handles: tapped rotation, hover highlight, click selection,
    /// and smooth position/rotation lerping for board updates.
    /// </summary>
    public class CardObject3D : MonoBehaviour
    {
        [Header("Card Dimensions (MTG standard ratio 63:88)")]
        [SerializeField] private float cardWidth = 0.63f;
        [SerializeField] private float cardHeight = 0.88f;
        [SerializeField] private float cardThickness = 0.02f;

        [Header("Animation")]
        [SerializeField] private float hoverLift = 0.15f;
        [SerializeField] private float lerpSpeed = 8f;
        [SerializeField] private float tapAngle = 90f;

        [Header("Materials")]
        [SerializeField] private Material cardBackMaterial;

        // Runtime state
        public BoardCard Data { get; private set; }
        public int CardId => Data?.id ?? -1;
        public bool IsTapped { get; private set; }
        public bool IsSelected { get; private set; }
        public int OwnerSeat => Data?.ownerSeat ?? 0;

        private Vector3 _targetPosition;
        private Quaternion _targetRotation;
        private bool _isHovered;
        private MeshRenderer _frontRenderer;
        private MeshRenderer _backRenderer;
        private Material _frontMaterial;
        private Collider _collider;
        private static readonly Color HighlightColor = new Color(1f, 0.9f, 0.3f, 1f);
        private static readonly Color SelectedColor = new Color(0.3f, 1f, 0.5f, 1f);
        private Color _baseEmission = Color.black;

        // ── Initialization ─────────────────────────────────────────

        public void Initialize(BoardCard data)
        {
            Data = data;
            gameObject.name = $"Card_{data.name}_{data.id}";
            BuildMesh();
            LoadTexture();
            SetTapped(data.tapped, instant: true);
        }

        private void BuildMesh()
        {
            // Front face (card art)
            var front = GameObject.CreatePrimitive(PrimitiveType.Quad);
            front.name = "Front";
            front.transform.SetParent(transform, false);
            front.transform.localScale = new Vector3(cardWidth, cardHeight, 1f);
            front.transform.localPosition = new Vector3(0, cardThickness / 2f, 0);
            front.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);

            _frontRenderer = front.GetComponent<MeshRenderer>();
            _frontMaterial = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            _frontMaterial.SetFloat("_Smoothness", 0.3f);
            _frontRenderer.material = _frontMaterial;

            // Back face
            var back = GameObject.CreatePrimitive(PrimitiveType.Quad);
            back.name = "Back";
            back.transform.SetParent(transform, false);
            back.transform.localScale = new Vector3(cardWidth, cardHeight, 1f);
            back.transform.localPosition = new Vector3(0, -cardThickness / 2f, 0);
            back.transform.localRotation = Quaternion.Euler(-90f, 0f, 0f);

            _backRenderer = back.GetComponent<MeshRenderer>();
            if (cardBackMaterial != null)
                _backRenderer.material = cardBackMaterial;
            else
            {
                var backMat = new Material(Shader.Find("Universal Render Pipeline/Lit"));
                backMat.color = new Color(0.15f, 0.1f, 0.25f);
                _backRenderer.material = backMat;
            }

            // Card body (thin box for thickness)
            var body = GameObject.CreatePrimitive(PrimitiveType.Cube);
            body.name = "Body";
            body.transform.SetParent(transform, false);
            body.transform.localScale = new Vector3(cardWidth, cardThickness, cardHeight);
            body.transform.localPosition = Vector3.zero;

            var bodyRenderer = body.GetComponent<MeshRenderer>();
            bodyRenderer.material = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            bodyRenderer.material.color = new Color(0.95f, 0.93f, 0.88f);

            // Use the body collider for raycasting
            _collider = body.GetComponent<Collider>();

            // Remove colliders from front/back quads
            Destroy(front.GetComponent<Collider>());
            Destroy(back.GetComponent<Collider>());
        }

        private void LoadTexture()
        {
            if (Data == null || string.IsNullOrEmpty(Data.imageUri)) return;

            // Use ImageCache if available, otherwise direct download
            if (ImageCache.Instance != null)
            {
                ImageCache.Instance.GetSprite(Data.imageUri, sprite =>
                {
                    if (sprite != null && _frontMaterial != null)
                    {
                        _frontMaterial.mainTexture = sprite.texture;
                    }
                });
            }
            else
            {
                StartCoroutine(DownloadTexture(Data.imageUri));
            }
        }

        private IEnumerator DownloadTexture(string url)
        {
            using var request = UnityEngine.Networking.UnityWebRequestTexture.GetTexture(url);
            yield return request.SendWebRequest();

            if (request.result == UnityEngine.Networking.UnityWebRequest.Result.Success)
            {
                var tex = UnityEngine.Networking.DownloadHandlerTexture.GetContent(request);
                if (_frontMaterial != null)
                    _frontMaterial.mainTexture = tex;
            }
        }

        // ── State Updates ──────────────────────────────────────────

        public void SetTapped(bool tapped, bool instant = false)
        {
            IsTapped = tapped;
            float yRot = tapped ? tapAngle : 0f;
            _targetRotation = Quaternion.Euler(0f, yRot, 0f);
            if (instant)
                transform.localRotation = _targetRotation;
        }

        public void SetTargetPosition(Vector3 pos)
        {
            _targetPosition = pos;
        }

        public void SetSelected(bool selected)
        {
            IsSelected = selected;
            UpdateEmission();
        }

        // ── Hover / Click (called by BoardManager raycast) ─────────

        public void OnHoverEnter()
        {
            _isHovered = true;
            UpdateEmission();
        }

        public void OnHoverExit()
        {
            _isHovered = false;
            UpdateEmission();
        }

        private void UpdateEmission()
        {
            if (_frontMaterial == null) return;

            Color emission;
            if (IsSelected)
                emission = SelectedColor * 0.5f;
            else if (_isHovered)
                emission = HighlightColor * 0.3f;
            else
                emission = _baseEmission;

            _frontMaterial.SetColor("_EmissionColor", emission);
            _frontMaterial.EnableKeyword("_EMISSION");
        }

        // ── Update Loop ────────────────────────────────────────────

        private void Update()
        {
            // Smooth position lerp
            float yOffset = _isHovered ? hoverLift : 0f;
            Vector3 target = _targetPosition + Vector3.up * yOffset;
            transform.localPosition = Vector3.Lerp(transform.localPosition, target,
                Time.deltaTime * lerpSpeed);

            // Smooth rotation lerp
            transform.localRotation = Quaternion.Slerp(transform.localRotation,
                _targetRotation, Time.deltaTime * lerpSpeed);
        }

        private void OnDestroy()
        {
            if (_frontMaterial != null) Destroy(_frontMaterial);
        }
    }
}
