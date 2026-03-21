using UnityEngine;

namespace CommanderAILab.Tabletop
{
    /// <summary>
    /// Generates the 3D tabletop surface at runtime.
    /// Creates an octagonal table with a felt-like surface material,
    /// wood-tone rim, and subtle player zone markings.
    /// </summary>
    public class TableMeshGenerator : MonoBehaviour
    {
        [Header("Table Dimensions")]
        [SerializeField] private float tableRadius = 5f;
        [SerializeField] private float tableHeight = 0.1f;
        [SerializeField] private float rimWidth = 0.15f;
        [SerializeField] private int segments = 8; // Octagonal

        [Header("Colors")]
        [SerializeField] private Color feltColor = new Color(0.05f, 0.25f, 0.12f); // Dark green felt
        [SerializeField] private Color rimColor = new Color(0.35f, 0.22f, 0.1f);    // Dark wood
        [SerializeField] private Color zoneLineColor = new Color(1f, 1f, 1f, 0.08f); // Faint white

        [Header("Lighting")]
        [SerializeField] private bool createOverheadLight = true;
        [SerializeField] private float lightHeight = 8f;
        [SerializeField] private float lightIntensity = 1.2f;

        private void Start()
        {
            CreateTableSurface();
            CreateRim();
            CreateZoneLines();
            if (createOverheadLight) CreateLight();
            CreateFloor();
        }

        // ── Table Surface (flat octagonal disc) ────────────────────

        private void CreateTableSurface()
        {
            var go = new GameObject("TableSurface");
            go.transform.SetParent(transform, false);

            var mesh = new Mesh();
            var mf = go.AddComponent<MeshFilter>();
            var mr = go.AddComponent<MeshRenderer>();

            // Generate octagon vertices
            int vCount = segments + 1;
            var vertices = new Vector3[vCount];
            var uvs = new Vector2[vCount];
            vertices[0] = Vector3.zero;
            uvs[0] = new Vector2(0.5f, 0.5f);

            for (int i = 0; i < segments; i++)
            {
                float angle = i * Mathf.PI * 2f / segments;
                float x = Mathf.Cos(angle) * tableRadius;
                float z = Mathf.Sin(angle) * tableRadius;
                vertices[i + 1] = new Vector3(x, 0, z);
                uvs[i + 1] = new Vector2(
                    0.5f + Mathf.Cos(angle) * 0.5f,
                    0.5f + Mathf.Sin(angle) * 0.5f);
            }

            // Triangles (fan from center)
            var triangles = new int[segments * 3];
            for (int i = 0; i < segments; i++)
            {
                triangles[i * 3] = 0;
                triangles[i * 3 + 1] = i + 1;
                triangles[i * 3 + 2] = (i + 1) % segments + 1;
            }

            mesh.vertices = vertices;
            mesh.uv = uvs;
            mesh.triangles = triangles;
            mesh.RecalculateNormals();
            mf.mesh = mesh;

            // Felt material
            var mat = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            mat.color = feltColor;
            mat.SetFloat("_Smoothness", 0.1f);
            mr.material = mat;

            // Collider for raycasting
            go.AddComponent<MeshCollider>().sharedMesh = mesh;
            go.layer = LayerMask.NameToLayer("Default");
        }

        // ── Rim (slightly raised ring around the edge) ─────────────

        private void CreateRim()
        {
            for (int i = 0; i < segments; i++)
            {
                float angle1 = i * Mathf.PI * 2f / segments;
                float angle2 = (i + 1) * Mathf.PI * 2f / segments;

                Vector3 inner1 = new Vector3(Mathf.Cos(angle1) * tableRadius, 0, Mathf.Sin(angle1) * tableRadius);
                Vector3 inner2 = new Vector3(Mathf.Cos(angle2) * tableRadius, 0, Mathf.Sin(angle2) * tableRadius);
                Vector3 outer1 = new Vector3(Mathf.Cos(angle1) * (tableRadius + rimWidth), 0,
                    Mathf.Sin(angle1) * (tableRadius + rimWidth));
                Vector3 outer2 = new Vector3(Mathf.Cos(angle2) * (tableRadius + rimWidth), 0,
                    Mathf.Sin(angle2) * (tableRadius + rimWidth));

                // Create rim segment as a cube stretched between corners
                Vector3 center = (inner1 + inner2 + outer1 + outer2) / 4f;
                center.y = tableHeight / 2f;

                var segment = GameObject.CreatePrimitive(PrimitiveType.Cube);
                segment.name = $"Rim_{i}";
                segment.transform.SetParent(transform, false);

                float length = Vector3.Distance(
                    (inner1 + outer1) / 2f,
                    (inner2 + outer2) / 2f);
                segment.transform.localScale = new Vector3(rimWidth, tableHeight, length);
                segment.transform.localPosition = center;

                float midAngle = (angle1 + angle2) / 2f;
                segment.transform.localRotation = Quaternion.Euler(0,
                    -midAngle * Mathf.Rad2Deg + 90f, 0);

                var mr = segment.GetComponent<MeshRenderer>();
                var mat = new Material(Shader.Find("Universal Render Pipeline/Lit"));
                mat.color = rimColor;
                mat.SetFloat("_Smoothness", 0.4f);
                mr.material = mat;
            }
        }

        // ── Zone divider lines (faint cross on the felt) ───────────

        private void CreateZoneLines()
        {
            // Create thin quads as zone dividers
            float lineWidth = 0.02f;
            float lineLength = tableRadius * 1.8f;

            // Horizontal line
            CreateLine("ZoneLine_H", Vector3.zero, lineLength, lineWidth, 0f);
            // Vertical line
            CreateLine("ZoneLine_V", Vector3.zero, lineLength, lineWidth, 90f);
        }

        private void CreateLine(string name, Vector3 center, float length, float width, float yRotation)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
            go.name = name;
            go.transform.SetParent(transform, false);
            go.transform.localPosition = new Vector3(center.x, 0.002f, center.z);
            go.transform.localRotation = Quaternion.Euler(90f, yRotation, 0f);
            go.transform.localScale = new Vector3(length, width, 1f);

            Destroy(go.GetComponent<Collider>());

            var mat = new Material(Shader.Find("Universal Render Pipeline/Unlit"));
            mat.color = zoneLineColor;
            // Make it transparent
            mat.SetFloat("_Surface", 1); // Transparent
            mat.SetFloat("_Blend", 0);
            mat.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            mat.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            mat.SetInt("_ZWrite", 0);
            mat.renderQueue = 3000;
            go.GetComponent<MeshRenderer>().material = mat;
        }

        // ── Overhead light ─────────────────────────────────────────

        private void CreateLight()
        {
            var lightObj = new GameObject("TableLight");
            lightObj.transform.SetParent(transform, false);
            lightObj.transform.localPosition = new Vector3(0, lightHeight, 0);
            lightObj.transform.localRotation = Quaternion.Euler(90f, 0, 0);

            var light = lightObj.AddComponent<Light>();
            light.type = LightType.Spot;
            light.intensity = lightIntensity;
            light.range = lightHeight * 2.5f;
            light.spotAngle = 80f;
            light.color = new Color(1f, 0.95f, 0.85f); // Warm white
            light.shadows = LightShadows.Soft;
        }

        // ── Floor plane (dark surface under the table) ─────────────

        private void CreateFloor()
        {
            var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.SetParent(transform, false);
            floor.transform.localPosition = new Vector3(0, -0.5f, 0);
            floor.transform.localScale = new Vector3(3f, 1f, 3f);

            var mat = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            mat.color = new Color(0.08f, 0.08f, 0.1f);
            mat.SetFloat("_Smoothness", 0.05f);
            floor.GetComponent<MeshRenderer>().material = mat;
        }
    }
}
