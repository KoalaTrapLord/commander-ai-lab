Shader "Eric/URP_AdditiveFlow_HDR"
{
    Properties
    {
        // 1. 保留此屬性增加兼容性
        [CanUseSpriteAtlas] 
        [MainTexture] _MainTex("Main Texture", 2D) = "white" {}
        [HDR] _TintColor("Tint Color (HDR)", Color) = (1, 1, 1, 1)
        _FlowSpeed("Flow Speed (XY)", Vector) = (0, 0, 0, 0)
        _Brightness("Brightness Boost", Float) = 1.0
        
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
        // 2. 加入 "PreviewType"="Plane" 是強制平面的關鍵
        Tags { 
            "RenderType" = "Transparent" 
            "Queue" = "Transparent" 
            "RenderPipeline" = "UniversalPipeline" 
            "PreviewType" = "Plane"
        }

        HLSLINCLUDE
        #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
        #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"
        ENDHLSL

        Pass
        {
            Blend One One
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma shader_feature _FRESNEL_ON
            #pragma shader_feature _SOFTPARTICLES_ON
            #pragma shader_feature _USEPARTICLEALPHADISSOLVE_ON

            struct Attributes {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                float4 color : COLOR;
                float3 normalOS : NORMAL;
            };

            struct Varyings {
                float4 positionCS : SV_POSITION;
                float4 screenPos : TEXCOORD0;
                float2 uv : TEXCOORD1;
                float4 color : COLOR;
                float3 viewDirWS : TEXCOORD3;
                float3 normalWS : TEXCOORD4;
                float eyeZ : TEXCOORD5; 
            };

            sampler2D _MainTex;
            sampler2D _DissolveTex;
            sampler2D _OverlayTex;

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float4 _DissolveTex_ST;
                float4 _OverlayTex_ST;
                float4 _TintColor;
                float4 _OverlayColor;
                float4 _FlowSpeed;
                float4 _OverlayFlowSpeed;
                float _Brightness;
                float4 _FresnelColor;
                float _FresnelPower;
                float _DistortStrength;
                float _DistortSpeed;
                float _DistortFrequency;
                float _SoftParticlesDistance;
                float _DissolveAmount;
                float _VertexAlphaRef;
                float4 _DissolveEdgeColor;
                float _DissolveEdgeWidth;
            CBUFFER_END

            Varyings vert(Attributes input) {
                Varyings output;
                float3 worldPos = TransformObjectToWorld(input.positionOS.xyz);
                float offset = sin(_Time.y * _DistortSpeed + (worldPos.x + worldPos.y + worldPos.z) * _DistortFrequency);
                input.positionOS.xyz += input.normalOS * offset * _DistortStrength;

                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.screenPos = ComputeScreenPos(output.positionCS);
                output.eyeZ = -TransformWorldToView(worldPos).z; 
                output.uv = input.uv;
                output.color = input.color;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.viewDirWS = GetWorldSpaceViewDir(worldPos);
                return output;
            }

            half4 frag(Varyings input) : SV_Target {
                float fade = 1.0;
                #ifdef _SOFTPARTICLES_ON
                    float2 screenUV = input.screenPos.xy / input.screenPos.w;
                    float rawDepth = SampleSceneDepth(screenUV);
                    float sceneZ, thisZ;
                    if (unity_OrthoParams.w > 0.5) {
                        #if UNITY_REVERSED_Z
                            sceneZ = (1.0 - rawDepth) * (_ProjectionParams.z - _ProjectionParams.y) + _ProjectionParams.y;
                        #else
                            sceneZ = rawDepth * (_ProjectionParams.z - _ProjectionParams.y) + _ProjectionParams.y;
                        #endif
                        thisZ = input.eyeZ;
                    } else {
                        sceneZ = LinearEyeDepth(rawDepth, _ZBufferParams);
                        thisZ = input.screenPos.w;
                    }
                    fade = saturate((sceneZ - thisZ) / _SoftParticlesDistance);
                #endif

                float currentDissolve = _DissolveAmount;
                #ifdef _USEPARTICLEALPHADISSOLVE_ON
                    float normalizedAlpha = saturate(input.color.a / max(0.001, _VertexAlphaRef));
                    currentDissolve = saturate(_DissolveAmount + (1.0 - normalizedAlpha));
                #endif

                float2 dissolveUV = input.uv * _DissolveTex_ST.xy + _DissolveTex_ST.zw;
                float dissolveValue = tex2D(_DissolveTex, dissolveUV).r;
                float dissolveMask = step(currentDissolve, dissolveValue + 0.001);
                float edgeMask = step(currentDissolve - _DissolveEdgeWidth, dissolveValue) * (1.0 - dissolveMask);
                edgeMask *= saturate(currentDissolve * 100.0);

                float2 mainUV = input.uv * _MainTex_ST.xy + _MainTex_ST.zw + _FlowSpeed.xy * _Time.y;
                half4 texColor = tex2D(_MainTex, mainUV);

                float2 overlayUV = input.uv * _OverlayTex_ST.xy + _OverlayTex_ST.zw + _OverlayFlowSpeed.xy * _Time.y;
                half4 overlayColor = tex2D(_OverlayTex, overlayUV) * _OverlayColor;

                float3 normal = normalize(input.normalWS);
                float3 viewDir = normalize(input.viewDirWS);
                float fresnel = saturate((1.0 - saturate(dot(normal, viewDir))) * _FresnelPower);
                
                half3 baseColor = texColor.rgb * _TintColor.rgb * input.color.rgb * overlayColor.rgb * _Brightness;
                #ifdef _FRESNEL_ON
                    baseColor += fresnel * _FresnelColor.rgb;
                #endif

                half3 finalRGB = (baseColor * dissolveMask) + (_DissolveEdgeColor.rgb * edgeMask);
                float finalAlpha = _TintColor.a * texColor.a * overlayColor.a * fade;
                #ifndef _USEPARTICLEALPHADISSOLVE_ON
                    finalAlpha *= input.color.a;
                #endif

                return half4(finalRGB * finalAlpha, 1.0);
            }
            ENDHLSL
        }
    }
}