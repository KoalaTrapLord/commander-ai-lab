Shader "Eric/Builtin_AlphaBlendFlow_HDR"
{
    Properties
    {
        [CanUseSpriteAtlas]
        [MainTexture] _MainTex("Main Texture", 2D) = "white" {}
        [HDR] _TintColor("Tint Color (HDR)", Color) = (1, 1, 1, 1)
        _FlowSpeed("Flow Speed (XY)", Vector) = (0, 0, 0, 0)
        _Brightness("Brightness Boost", Float) = 1.0
        _AlphaCutoff("Alpha Cutoff", Range(0, 1)) = 0.0

        [Header(Fresnel Rim Light)]
        [Toggle(_FRESNEL_ON)] _UseFresnel("Enable Fresnel", Float) = 0
        [HDR] _FresnelColor("Fresnel Color", Color) = (1, 1, 1, 1)
        _FresnelPower("Fresnel Power", Range(0, 10.0)) = 1.0

        [Header(Soft Particles)]
        [Toggle(_SOFTPARTICLES_ON)] _SoftParticlesEnabled("Enable Soft Particles", Float) = 0
        _SoftParticlesDistance("Soft Particles Distance", Range(0.01, 5.0)) = 1.0

        [Header(Dissolve Settings)]
        [Toggle(_USEPARTICLEALPHADISSOLVE_ON)] _UseParticleAlphaDissolve("Use Particle Alpha as Dissolve?", Float) = 0
        _DissolveTex("Dissolve Texture (Noise)", 2D) = "white" {}
        _DissolveAmount("Dissolve Amount (Manual)", Range(0, 1)) = 0.0
        _VertexAlphaRef("Dissolve Alpha Ref (頂點Alpha基準)", Range(0.01, 1.0)) = 1.0
        [HDR] _DissolveEdgeColor("Dissolve Edge Color", Color) = (1, 0, 0, 1)
        _DissolveEdgeWidth("Dissolve Edge Width", Range(0, 0.2)) = 0.05

        [Header(Overlay and Distortion)]
        _OverlayTex("Overlay Texture", 2D) = "white" {}
        [HDR] _OverlayColor("Overlay Color", Color) = (1, 1, 1, 1)
        _OverlayFlowSpeed("Overlay Flow Speed", Vector) = (0, 0, 0, 0)
        _DistortStrength("Distort Strength", Range(0, 0.5)) = 0.0
        _DistortSpeed("Distort Speed", Float) = 1.0
        _DistortFrequency("Distort Frequency", Float) = 2.0
    }

    SubShader
    {
        Tags { "Queue"="Transparent" "IgnoreProjector"="True" "RenderType"="Transparent" "PreviewType"="Plane" }
        
        Pass
        {
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #pragma shader_feature _FRESNEL_ON
            #pragma shader_feature _SOFTPARTICLES_ON
            #pragma shader_feature _USEPARTICLEALPHADISSOLVE_ON

            #include "UnityCG.cginc"

            struct appdata {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
                float4 color : COLOR;
                float3 normal : NORMAL;
            };

            struct v2f {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float4 color : COLOR;
                float4 screenPos : TEXCOORD1;
                float3 viewDir : TEXCOORD3;
                float3 normalWS : TEXCOORD4;
                float eyeZ : TEXCOORD5;
                UNITY_FOG_COORDS(6)
            };

            sampler2D _MainTex; float4 _MainTex_ST;
            sampler2D _DissolveTex; float4 _DissolveTex_ST;
            sampler2D _OverlayTex; float4 _OverlayTex_ST;
            sampler2D_float _CameraDepthTexture;

            float4 _TintColor, _OverlayColor, _FlowSpeed, _OverlayFlowSpeed, _DissolveEdgeColor, _FresnelColor;
            float _Brightness, _AlphaCutoff, _FresnelPower, _SoftParticlesDistance, _DissolveAmount, _VertexAlphaRef, _DissolveEdgeWidth;
            float _DistortStrength, _DistortSpeed, _DistortFrequency;

            v2f vert (appdata v) {
                v2f o;
                float3 worldPos = mul(unity_ObjectToWorld, v.vertex).xyz;
                float offset = sin(_Time.y * _DistortSpeed + (worldPos.x + worldPos.y + worldPos.z) * _DistortFrequency);
                v.vertex.xyz += v.normal * offset * _DistortStrength;

                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                o.color = v.color;
                o.screenPos = ComputeScreenPos(o.pos);
                o.eyeZ = -UnityObjectToViewPos(v.vertex).z;
                o.normalWS = UnityObjectToWorldNormal(v.normal);
                o.viewDir = WorldSpaceViewDir(v.vertex);
                UNITY_TRANSFER_FOG(o, o.pos);
                return o;
            }

            fixed4 frag (v2f i) : SV_Target {
                float fade = 1.0;
                #ifdef _SOFTPARTICLES_ON
                    float sceneZ = LinearEyeDepth(SAMPLE_DEPTH_TEXTURE_PROJ(_CameraDepthTexture, UNITY_PROJ_COORD(i.screenPos)));
                    float thisZ = i.screenPos.w;
                    if(unity_OrthoParams.w > 0.5) { thisZ = i.eyeZ; }
                    fade = saturate((sceneZ - thisZ) / _SoftParticlesDistance);
                #endif

                float currentDissolve = _DissolveAmount;
                #ifdef _USEPARTICLEALPHADISSOLVE_ON
                    float normalizedAlpha = saturate(i.color.a / max(0.001, _VertexAlphaRef));
                    currentDissolve = saturate(_DissolveAmount + (1.0 - normalizedAlpha));
                #endif

                float2 dissolveUV = TRANSFORM_TEX(i.uv, _DissolveTex);
                float dissolveValue = tex2D(_DissolveTex, dissolveUV).r;
                float dissolveMask = step(currentDissolve, dissolveValue + 0.001);
                float edgeMask = step(currentDissolve - _DissolveEdgeWidth, dissolveValue) * (1.0 - dissolveMask);
                edgeMask *= saturate(currentDissolve * 100.0);

                if (dissolveMask + edgeMask < 0.01) discard;

                float2 mainUV = TRANSFORM_TEX(i.uv, _MainTex) + _FlowSpeed.xy * _Time.y;
                float4 texColor = tex2D(_MainTex, mainUV);

                float2 overlayUV = TRANSFORM_TEX(i.uv, _OverlayTex) + _OverlayFlowSpeed.xy * _Time.y;
                float4 overlayColor = tex2D(_OverlayTex, overlayUV) * _OverlayColor;

                float3 normal = normalize(i.normalWS);
                float3 viewDir = normalize(i.viewDir);
                float fresnel = pow(1.0 - saturate(dot(normal, viewDir)), _FresnelPower);

                float3 baseColor = texColor.rgb * _TintColor.rgb * i.color.rgb * overlayColor.rgb * _Brightness;
                #ifdef _FRESNEL_ON
                    baseColor += fresnel * _FresnelColor.rgb;
                #endif

                float3 finalColor = (baseColor * dissolveMask) + (_DissolveEdgeColor.rgb * edgeMask);
                float finalAlpha = texColor.a * _TintColor.a * overlayColor.a * fade;
                #ifndef _USEPARTICLEALPHADISSOLVE_ON
                    finalAlpha *= i.color.a;
                #endif

                if (finalAlpha < _AlphaCutoff) discard;

                fixed4 col = fixed4(finalColor, finalAlpha);
                UNITY_APPLY_FOG(i.fogCoord, col);
                return col;
            }
            ENDCG
        }
    }
}